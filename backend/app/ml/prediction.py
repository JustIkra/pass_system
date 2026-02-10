"""Prediction module: load trained Prophet models and generate forecasts.

Typical usage::

    from app.ml.prediction import load_models, generate_forecast, save_forecast_to_db

    models = load_models("/path/to/models")
    points = generate_forecast(branch_id=176, year=2026, month=3, models=models)
    save_forecast_to_db(db_session, branch_id=176, forecasts=points)

    # Arbitrary date range forecast:
    from app.ml.prediction import generate_forecast_range
    points = generate_forecast_range(
        branch_id=176,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 30),
        models=models,
    )
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
from app.ml.postprocessing import postprocess_forecast

logger = logging.getLogger(__name__)

# Working hours (inclusive start, exclusive end): 08:00 .. 19:59
WORKING_HOURS: list[int] = list(range(8, 20))

# Fallback safety cap for predicted wait time (minutes) when model has no stored cap.
# Per-branch caps are stored at training time in model metadata.
# This global fallback is based on historical P99.9 (~60 min) across all branches.
_FALLBACK_MAX_WAIT_MINUTES: float = 60.0


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


def _build_future_df_range(start_date: date, end_date: date) -> pd.DataFrame:
    """Create a future DataFrame for all working hours from *start_date* to *end_date* inclusive.

    Excludes Sundays and Russian public holidays.
    """
    rows: list[dict[str, Any]] = []
    current = start_date

    while current <= end_date:
        # Skip Sundays
        if current.weekday() == 6:
            current += timedelta(days=1)
            continue

        # Skip public holidays
        if is_russian_holiday(current):
            current += timedelta(days=1)
            continue

        for hour in WORKING_HOURS:
            dt = datetime(current.year, current.month, current.day, hour)
            rows.append({"ds": dt})

        current += timedelta(days=1)

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
    apply_postprocessing: bool = True,
    db_session: Session | None = None,
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
    apply_postprocessing:
        If ``True`` (default), applies capacity constraints and smoothing to the forecast.
    db_session:
        Optional DB session for postprocessing metadata queries. Required if
        ``apply_postprocessing=True``.

    Returns
    -------
    list[ForecastPoint]
        One entry per working hour in the requested month.

    Raises
    ------
    KeyError
        If *branch_id* is not found in *models*.
    ValueError
        If ``apply_postprocessing=True`` and ``db_session`` is ``None``.
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

    # Predict wait (also log1p-transformed, logistic growth needs cap/floor)
    wait_future = future[["ds"] + REGRESSOR_COLUMNS].copy()
    if wait_model.growth == "logistic":
        if hasattr(wait_model, "history") and "cap" in wait_model.history.columns:
            wait_future["cap"] = float(wait_model.history["cap"].iloc[0])
        else:
            wait_future["cap"] = float(np.log1p(_FALLBACK_MAX_WAIT_MINUTES))
        wait_future["floor"] = 0.0

    wait_fc = wait_model.predict(wait_future)

    # Clamp log-scale yhat using per-model cap (from training) or global fallback.
    # This prevents expm1 explosion from log-scale overshoot.
    model_log_cap = getattr(wait_model, "wait_log_cap", None)
    if model_log_cap is None:
        model_log_cap = float(np.log1p(_FALLBACK_MAX_WAIT_MINUTES))
    wait_fc["yhat"] = wait_fc["yhat"].clip(upper=model_log_cap)
    wait_fc["yhat_lower"] = wait_fc["yhat_lower"].clip(upper=model_log_cap)
    wait_fc["yhat_upper"] = wait_fc["yhat_upper"].clip(upper=model_log_cap)

    # Inverse log1p transform (models trained on log-scale)
    visits_fc["predicted_visits"] = np.maximum(np.expm1(visits_fc["yhat"].values), 0.0)
    visits_fc["confidence_lower"] = np.maximum(np.expm1(visits_fc["yhat_lower"].values), 0.0)
    visits_fc["confidence_upper"] = np.maximum(np.expm1(visits_fc["yhat_upper"].values), 0.0)
    wait_fc["predicted_avg_wait"] = np.maximum(np.expm1(wait_fc["yhat"].values), 0.0)

    # Extract date and hour for postprocessing
    visits_fc["date"] = visits_fc["ds"].dt.strftime("%Y-%m-%d")
    visits_fc["hour"] = visits_fc["ds"].dt.hour

    # Apply postprocessing if requested
    if apply_postprocessing:
        if db_session is None:
            raise ValueError(
                "apply_postprocessing=True requires db_session parameter"
            )
        # Create DataFrame compatible with postprocess_forecast
        forecast_df = pd.DataFrame({
            "date": visits_fc["date"],
            "hour": visits_fc["hour"],
            "predicted_visits": visits_fc["predicted_visits"],
        })
        forecast_df = postprocess_forecast(
            forecast_df, branch_id, db_session,
            apply_smoothing=True, correct_outliers=True
        )
        # Update with postprocessed values
        visits_fc["predicted_visits"] = forecast_df["predicted_visits"].values

    # Build ForecastPoint objects
    points: list[ForecastPoint] = []
    for i in range(len(visits_fc)):
        row_v = visits_fc.iloc[i]
        row_w = wait_fc.iloc[i]
        ds: pd.Timestamp = row_v["ds"]

        predicted_visits = max(0.0, round(float(row_v["predicted_visits"]), 1))
        predicted_avg_wait = max(0.0, round(float(row_w["predicted_avg_wait"]), 1))
        confidence_lower = max(0.0, round(float(row_v["confidence_lower"]), 1))
        confidence_upper = max(0.0, round(float(row_v["confidence_upper"]), 1))

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
        "Generated %d forecast points for branch %d (%d-%02d)%s",
        len(points), branch_id, year, month,
        " [postprocessed]" if apply_postprocessing else "",
    )
    return points


def generate_forecast_range(
    branch_id: int,
    start_date: date,
    end_date: date,
    models: dict[int, tuple[Prophet, Prophet]],
    apply_postprocessing: bool = True,
    db_session: Session | None = None,
) -> list[ForecastPoint]:
    """Generate an hourly forecast for *branch_id* over an arbitrary date range.

    Parameters
    ----------
    branch_id:
        Target branch.
    start_date, end_date:
        Inclusive date boundaries for the forecast period.
    models:
        Pre-loaded model dictionary (see :func:`load_models`).
    apply_postprocessing:
        If ``True`` (default), applies capacity constraints and smoothing to the forecast.
    db_session:
        Optional DB session for postprocessing metadata queries. Required if
        ``apply_postprocessing=True``.

    Returns
    -------
    list[ForecastPoint]
        One entry per working hour in the requested date range.

    Raises
    ------
    KeyError
        If *branch_id* is not found in *models*.
    ValueError
        If *start_date* > *end_date* or if ``apply_postprocessing=True``
        and ``db_session`` is ``None``.
    """
    if start_date > end_date:
        raise ValueError(
            f"start_date ({start_date}) must be <= end_date ({end_date})"
        )

    if branch_id not in models:
        raise KeyError(f"No trained model for branch_id={branch_id}")

    visits_model, wait_model = models[branch_id]

    future = _build_future_df_range(start_date, end_date)
    if future.empty:
        logger.warning(
            "Empty future for %s .. %s (no working hours?)", start_date, end_date,
        )
        return []

    # Predict visits (model was trained on log1p-transformed data)
    visits_fc = visits_model.predict(
        future[["ds"] + REGRESSOR_COLUMNS]
    )

    # Predict wait (also log1p-transformed, logistic growth needs cap/floor)
    wait_future = future[["ds"] + REGRESSOR_COLUMNS].copy()
    if wait_model.growth == "logistic":
        if hasattr(wait_model, "history") and "cap" in wait_model.history.columns:
            wait_future["cap"] = float(wait_model.history["cap"].iloc[0])
        else:
            wait_future["cap"] = float(np.log1p(_FALLBACK_MAX_WAIT_MINUTES))
        wait_future["floor"] = 0.0

    wait_fc = wait_model.predict(wait_future)

    # Clamp log-scale yhat using per-model cap (from training) or global fallback.
    model_log_cap = getattr(wait_model, "wait_log_cap", None)
    if model_log_cap is None:
        model_log_cap = float(np.log1p(_FALLBACK_MAX_WAIT_MINUTES))
    wait_fc["yhat"] = wait_fc["yhat"].clip(upper=model_log_cap)
    wait_fc["yhat_lower"] = wait_fc["yhat_lower"].clip(upper=model_log_cap)
    wait_fc["yhat_upper"] = wait_fc["yhat_upper"].clip(upper=model_log_cap)

    # Inverse log1p transform (models trained on log-scale)
    visits_fc["predicted_visits"] = np.maximum(np.expm1(visits_fc["yhat"].values), 0.0)
    visits_fc["confidence_lower"] = np.maximum(np.expm1(visits_fc["yhat_lower"].values), 0.0)
    visits_fc["confidence_upper"] = np.maximum(np.expm1(visits_fc["yhat_upper"].values), 0.0)
    wait_fc["predicted_avg_wait"] = np.maximum(np.expm1(wait_fc["yhat"].values), 0.0)

    # Extract date and hour for postprocessing
    visits_fc["date"] = visits_fc["ds"].dt.strftime("%Y-%m-%d")
    visits_fc["hour"] = visits_fc["ds"].dt.hour

    # Apply postprocessing if requested
    if apply_postprocessing:
        if db_session is None:
            raise ValueError(
                "apply_postprocessing=True requires db_session parameter"
            )
        # Create DataFrame compatible with postprocess_forecast
        forecast_df = pd.DataFrame({
            "date": visits_fc["date"],
            "hour": visits_fc["hour"],
            "predicted_visits": visits_fc["predicted_visits"],
        })
        forecast_df = postprocess_forecast(
            forecast_df, branch_id, db_session,
            apply_smoothing=True, correct_outliers=True
        )
        # Update with postprocessed values
        visits_fc["predicted_visits"] = forecast_df["predicted_visits"].values

    # Build ForecastPoint objects
    points: list[ForecastPoint] = []
    for i in range(len(visits_fc)):
        row_v = visits_fc.iloc[i]
        row_w = wait_fc.iloc[i]
        ds: pd.Timestamp = row_v["ds"]

        predicted_visits = max(0.0, round(float(row_v["predicted_visits"]), 1))
        predicted_avg_wait = max(0.0, round(float(row_w["predicted_avg_wait"]), 1))
        confidence_lower = max(0.0, round(float(row_v["confidence_lower"]), 1))
        confidence_upper = max(0.0, round(float(row_v["confidence_upper"]), 1))

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
        "Generated %d forecast points for branch %d (%s .. %s)%s",
        len(points), branch_id, start_date, end_date,
        " [postprocessed]" if apply_postprocessing else "",
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
                     predicted_avg_service, confidence_lower, confidence_upper, created_at)
                VALUES
                    (:branch_id, :date, :hour, :predicted_visits, :predicted_avg_wait,
                     :predicted_avg_service, :confidence_lower, :confidence_upper, NOW())
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
