"""API router for data upload and model management endpoints."""

from __future__ import annotations

import io
import logging
import threading
import time
from datetime import date, datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Form
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.schemas import (
    ForecastGenerateRequest,
    ForecastGenerateResponse,
    ForecastGenerationStatus,
    ModelRetrainResponse,
    ModelStatusResponse,
    UploadResponse,
)
from app.services.etl import (
    _parse_queue_csv as parse_queue_csv,
    _parse_roles_csv as parse_roles_csv,
    parse_employees_csv,
    aggregate_hourly_stats,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data"])

# In-memory model training state (single-process MVP)
_training_state: dict = {
    "status": "idle",
    "progress": 0,
    "total_branches": 0,
    "current_branch": None,
    "started_at": None,
}

# In-memory forecast generation state
_generation_state: dict = {
    "status": "idle",
    "progress": 0,
    "total_branches": 0,
    "current_branch_name": None,
    "started_at": None,
    "error_message": None,
}

# Expected CSV columns by type
_EXPECTED_COLUMNS = {
    "queue": {"Branch_ID", "Customer_number_Queue", "Data_zapis", "Time_zapis"},
    "roles": {"Employee_ID", "Branch_ID", "Date_begin", "Time_begin"},
    "employees": {"Employee_ID", "FIO", "Tab_num", "Branch"},
}


@router.post("/api/data/upload", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    type: str = Form(..., description="CSV type: queue, roles, or employees"),
    db: Session = Depends(get_db),
) -> dict:
    """Upload a new CSV file and load it into the database."""
    if type not in _EXPECTED_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type '{type}'. Must be one of: queue, roles, employees",
        )

    start = time.time()

    content = await file.read()
    try:
        df = pd.read_csv(
            io.BytesIO(content),
            sep=";",
            encoding="utf-8",
            nrows=5,
            dtype=str,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSV format: {exc}")

    # Validate columns
    csv_cols = {c.strip() for c in df.columns}
    required = _EXPECTED_COLUMNS[type]
    missing = required - csv_cols
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid CSV format. Missing columns: {missing}",
        )

    # Save temp file and process
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".csv", mode="wb"
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        records_loaded = 0
        records_skipped = 0

        if type == "queue":
            # We need to use the directory containing the temp file
            # But our parser expects a directory with glob patterns
            # So we temporarily rename the file
            import shutil

            tmp_dir = tempfile.mkdtemp()
            dest = os.path.join(tmp_dir, "Статистика ЭО для WMF (upload).csv")
            shutil.copy(tmp_path, dest)
            loaded, skipped = parse_queue_csv(tmp_dir, db)
            records_loaded = loaded
            records_skipped = skipped
            aggregate_hourly_stats(db)
            shutil.rmtree(tmp_dir, ignore_errors=True)

        elif type == "roles":
            tmp_dir = tempfile.mkdtemp()
            dest = os.path.join(tmp_dir, "Журнал ролей специалистов (upload).csv")
            import shutil
            shutil.copy(tmp_path, dest)
            records_loaded = parse_roles_csv(tmp_dir, db)
            shutil.rmtree(tmp_dir, ignore_errors=True)

        elif type == "employees":
            tmp_dir = tempfile.mkdtemp()
            dest = os.path.join(tmp_dir, "Справочник специалистов (upload).csv")
            import shutil
            shutil.copy(tmp_path, dest)
            records_loaded = parse_employees_csv(tmp_dir, db)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    finally:
        os.unlink(tmp_path)

    duration = round(time.time() - start, 1)

    return {
        "status": "ok",
        "records_loaded": records_loaded,
        "records_skipped": records_skipped,
        "duration_seconds": duration,
    }


@router.post("/api/model/retrain", response_model=ModelRetrainResponse, status_code=202)
def retrain_model() -> dict:
    """Trigger model retraining (asynchronous, placeholder for MVP)."""
    from datetime import datetime

    _training_state["status"] = "training_started"
    _training_state["progress"] = 0
    _training_state["total_branches"] = 44
    _training_state["current_branch"] = None
    _training_state["started_at"] = datetime.utcnow().isoformat()

    return {
        "status": "training_started",
        "message": "Model retraining initiated for 44 branches. Check /api/model/status for progress.",
    }


@router.get("/api/model/status", response_model=ModelStatusResponse)
def model_status() -> dict:
    """Return current model training status."""
    return {
        "status": _training_state["status"],
        "progress": _training_state["progress"],
        "total_branches": _training_state["total_branches"],
        "current_branch": _training_state["current_branch"],
        "started_at": _training_state["started_at"],
    }


# ---------------------------------------------------------------------------
# Forecast generation endpoints
# ---------------------------------------------------------------------------


def _run_forecast_generation(
    branch_ids: list[int],
    start_date: date,
    end_date: date,
    branch_names: dict[int, str],
) -> None:
    """Background worker: generate forecasts for the given branches."""
    from app.ml.prediction import (
        generate_forecast_range,
        load_models,
        save_forecast_to_db,
    )

    try:
        models = load_models(settings.MODELS_DIR)
        if not models:
            _generation_state["status"] = "error"
            _generation_state["error_message"] = "Модели не найдены. Сначала обучите модели."
            return

        # Filter to only branches that have models
        valid_ids = [bid for bid in branch_ids if bid in models]
        _generation_state["total_branches"] = len(valid_ids)

        if not valid_ids:
            _generation_state["status"] = "error"
            _generation_state["error_message"] = "Нет обученных моделей для выбранных филиалов."
            return

        for i, bid in enumerate(valid_ids):
            _generation_state["progress"] = i
            _generation_state["current_branch_name"] = branch_names.get(bid, str(bid))

            try:
                points = generate_forecast_range(
                    branch_id=bid,
                    start_date=start_date,
                    end_date=end_date,
                    models=models,
                )
                db = SessionLocal()
                try:
                    save_forecast_to_db(db, bid, points)
                finally:
                    db.close()
            except Exception:
                logger.exception("Failed to generate forecast for branch %d", bid)

        _generation_state["progress"] = len(valid_ids)
        _generation_state["current_branch_name"] = None
        _generation_state["status"] = "completed"

    except Exception as exc:
        logger.exception("Forecast generation failed")
        _generation_state["status"] = "error"
        _generation_state["error_message"] = str(exc)


@router.post(
    "/api/forecast/generate",
    response_model=ForecastGenerateResponse,
    status_code=202,
)
def generate_forecast(
    req: ForecastGenerateRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Start forecast generation in the background."""
    if _generation_state["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail="Генерация уже выполняется. Дождитесь завершения.",
        )

    try:
        start_date = date.fromisoformat(req.from_date)
        end_date = date.fromisoformat(req.to_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Неверный формат даты. Используйте YYYY-MM-DD.",
        )

    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="from_date должна быть <= to_date.",
        )

    # Determine target branches
    from sqlalchemy import text

    if req.branch_id is not None:
        rows = db.execute(
            text("SELECT id, COALESCE(name, CAST(id AS TEXT)) as name FROM branches WHERE id = :bid"),
            {"bid": req.branch_id},
        ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="Филиал не найден.")
    else:
        rows = db.execute(
            text("SELECT id, COALESCE(name, CAST(id AS TEXT)) as name FROM branches")
        ).fetchall()

    branch_ids = [r[0] for r in rows]
    branch_names = {r[0]: r[1] for r in rows}

    # Reset state
    _generation_state["status"] = "running"
    _generation_state["progress"] = 0
    _generation_state["total_branches"] = len(branch_ids)
    _generation_state["current_branch_name"] = None
    _generation_state["started_at"] = datetime.utcnow().isoformat()
    _generation_state["error_message"] = None

    thread = threading.Thread(
        target=_run_forecast_generation,
        args=(branch_ids, start_date, end_date, branch_names),
        daemon=True,
    )
    thread.start()

    return {
        "status": "started",
        "message": f"Генерация прогноза запущена для {len(branch_ids)} филиалов.",
        "total_branches": len(branch_ids),
    }


@router.get("/api/forecast/status", response_model=ForecastGenerationStatus)
def forecast_generation_status() -> dict:
    """Return current forecast generation status."""
    return {
        "status": _generation_state["status"],
        "progress": _generation_state["progress"],
        "total_branches": _generation_state["total_branches"],
        "current_branch_name": _generation_state["current_branch_name"],
        "started_at": _generation_state["started_at"],
        "error_message": _generation_state["error_message"],
    }
