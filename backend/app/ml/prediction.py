"""Prediction module: load trained Prophet models and generate forecasts.

Typical usage::

    from app.ml.prediction import load_models, generate_forecast, save_forecast_to_db

    models = load_models("/path/to/models")
    points = generate_forecast(branch_id=176, year=2026, month=3, models=models)
    save_forecast_to_db(db_session, branch_id=176, forecasts=points)
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from prophet import Prophet
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ml.utils import REGRESSOR_COLUMNS, add_regressors, is_russian_holiday

logger = logging.getLogger(__name__)

# Working hours (inclusive start, exclusive end): 08:00 .. 19:59
WORKING_HOURS: list[int] = list(range(8, 20))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ForecastPoint:
    """A single hourly forecast data point."""

    date: str             # "YYYY-MM-DD"
    hour: int             # 8..19
    predicted_visits: float
    predicted_avg_wait: float
    confidence_lower: float
    confidence_upper: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_models(models_dir: str | Path) -> dict[int, tuple[Prophet, Prophet]]:
    """Load all trained Prophet model pairs from *models_dir*.

    Scans for files matching ``branch_{id}_visits.pkl`` and
    ``branch_{id}_wait.pkl``.

    Returns
    -------
    dict[int, tuple[Prophet, Prophet]]
        Mapping ``branch_id -> (visits_model, wait_model)``.
    """
    models_dir = Path(models_dir)
    models: dict[int, tuple[Prophet, Prophet]] = {}

    if not models_dir.exists():
        logger.warning("Models directory does not exist: %s", models_dir)
        return models

    visit_files = sorted(models_dir.glob("branch_*_visits.pkl"))
    for vf in visit_files:
        stem = vf.stem  # e.g. "branch_176_visits"
        parts = stem.split("_")
        try:
            branch_id = int(parts[1])
        except (IndexError, ValueError):
            logger.warning("Cannot parse branch id from %s", vf.name)
            continue

        wait_file = models_dir / f"branch_{branch_id}_wait.pkl"
        if not wait_file.exists():
            logger.warning("Missing wait model for branch %d, skipping", branch_id)
            continue

        try:
            visits_model: Prophet = joblib.load(vf)
            wait_model: Prophet = joblib.load(wait_file)
            models[branch_id] = (visits_model, wait_model)
        except Exception:
            logger.exception("Failed to load models for branch %d", branch_id)

    logger.info("Loaded models for %d branches from %s", len(models), models_dir)
    return models


# ---------------------------------------------------------------------------
# Future dataframe generation
# ---------------------------------------------------------------------------

def _build_future_df(year: int, month: int) -> pd.DataFrame:
    """Create a future DataFrame for all working hours in *year*-*month*.

    Excludes Sundays and Russian public holidays.
    """
    num_days = calendar.monthrange(year, month)[1]
    rows: list[dict[str, Any]] = []

    for day in range(1, num_days + 1):
        d = date(year, month, day)

        # Skip Sundays
        if d.weekday() == 6:
            continue

        # Skip public holidays
        if is_russian_holiday(d):
            continue

        for hour in WORKING_HOURS:
            dt = datetime(year, month, day, hour)
            rows.append({"ds": dt})

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ds"] = pd.to_datetime(df["ds"])
    df = add_regressors(df)
    return df


# ---------------------------------------------------------------------------
# Forecast generation
# ---------------------------------------------------------------------------

def generate_forecast(
    branch_id: int,
    year: int,
    month: int,
    models: dict[int, tuple[Prophet, Prophet]],
) -> list[ForecastPoint]:
    """Generate an hourly forecast for *branch_id* over *year*-*month*.

    Parameters
    ----------
    branch_id:
        Target branch.
    year, month:
        Target period.
    models:
        Pre-loaded model dictionary (see :func:`load_models`).

    Returns
    -------
    list[ForecastPoint]
        One entry per working hour in the requested month.

    Raises
    ------
    KeyError
        If *branch_id* is not found in *models*.
    """
    if branch_id not in models:
        raise KeyError(f"No trained model for branch_id={branch_id}")

    visits_model, wait_model = models[branch_id]

    future = _build_future_df(year, month)
    if future.empty:
        logger.warning("Empty future for %d-%02d (no working hours?)", year, month)
        return []

    # Predict visits (model was trained on log1p-transformed data)
    visits_fc = visits_model.predict(
        future[["ds"] + REGRESSOR_COLUMNS]
    )

    # Predict wait (also log1p-transformed)
    wait_fc = wait_model.predict(
        future[["ds"] + REGRESSOR_COLUMNS]
    )

    points: list[ForecastPoint] = []
    for i in range(len(visits_fc)):
        row_v = visits_fc.iloc[i]
        row_w = wait_fc.iloc[i]
        ds: pd.Timestamp = row_v["ds"]

        # Inverse log1p transform (models trained on log-scale)
        predicted_visits = max(0.0, round(float(np.expm1(row_v["yhat"])), 1))
        predicted_avg_wait = max(0.0, round(float(np.expm1(row_w["yhat"])), 1))
        confidence_lower = max(0.0, round(float(np.expm1(row_v["yhat_lower"])), 1))
        confidence_upper = max(0.0, round(float(np.expm1(row_v["yhat_upper"])), 1))

        points.append(
            ForecastPoint(
                date=ds.strftime("%Y-%m-%d"),
                hour=ds.hour,
                predicted_visits=predicted_visits,
                predicted_avg_wait=predicted_avg_wait,
                confidence_lower=confidence_lower,
                confidence_upper=confidence_upper,
            )
        )

    logger.info(
        "Generated %d forecast points for branch %d (%d-%02d)",
        len(points), branch_id, year, month,
    )
    return points


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_forecast_to_db(
    db_session: Session,
    branch_id: int,
    forecasts: list[ForecastPoint],
) -> int:
    """Write forecast points into the ``forecasts`` table.

    Existing records for the same ``(branch_id, date, hour)`` are deleted
    first (upsert behaviour).

    Returns the number of rows inserted.
    """
    if not forecasts:
        return 0

    # Determine affected month for bulk delete
    dates = {fp.date for fp in forecasts}
    min_date = min(dates)
    max_date = max(dates)

    db_session.execute(
        text(
            """
            DELETE FROM forecasts
            WHERE branch_id = :bid AND date >= :d_min AND date <= :d_max
            """
        ),
        {"bid": branch_id, "d_min": min_date, "d_max": max_date},
    )

    rows: list[dict[str, Any]] = []
    for fp in forecasts:
        rows.append(
            {
                "branch_id": branch_id,
                "date": fp.date,
                "hour": fp.hour,
                "predicted_visits": fp.predicted_visits,
                "predicted_avg_wait": fp.predicted_avg_wait,
                "predicted_avg_service": None,
                "confidence_lower": fp.confidence_lower,
                "confidence_upper": fp.confidence_upper,
            }
        )

    if rows:
        db_session.execute(
            text(
                """
                INSERT INTO forecasts
                    (branch_id, date, hour, predicted_visits, predicted_avg_wait,
                     predicted_avg_service, confidence_lower, confidence_upper)
                VALUES
                    (:branch_id, :date, :hour, :predicted_visits, :predicted_avg_wait,
                     :predicted_avg_service, :confidence_lower, :confidence_upper)
                """
            ),
            rows,
        )
        db_session.commit()

    logger.info(
        "Saved %d forecast rows for branch %d (%s .. %s)",
        len(rows), branch_id, min_date, max_date,
    )
    return len(rows)
