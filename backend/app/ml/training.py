"""Training pipeline for Prophet models (visits + wait per branch).

Each branch gets two Prophet models:
* **visits** -- forecasts ``total_visits`` per hour
* **wait**   -- forecasts ``avg_wait_seconds`` per hour

Models are serialised with :pymod:`joblib` into *models_dir*.

Supports parallel training across all CPU cores via ProcessPoolExecutor.
Supports GPU-accelerated MCMC sampling via CmdStanPy OpenCL backend.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from prophet import Prophet
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ml.gpu_utils import configure_cmdstanpy_gpu, detect_gpu
from app.ml.utils import (
    REGRESSOR_COLUMNS,
    add_regressors,
    calculate_ci_coverage,
    calculate_mae,
    calculate_mape,
    calculate_peak_accuracy,
    calculate_rmse,
    get_russian_holidays_df,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKING_HOURS: list[int] = list(range(8, 20))  # 8:00 .. 19:00 (last slot ends 20:00)
MIN_DATA_POINTS: int = 30 * len(WORKING_HOURS)  # ~30 working days

# Prophet suppresses its own logs at INFO level; we keep it quiet.
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def prepare_training_data(
    db_session: Session,
    branch_id: int,
    target: str = "total_visits",
) -> pd.DataFrame:
    """Fetch ``hourly_stats`` for *branch_id* and reshape into Prophet format.

    Parameters
    ----------
    db_session:
        Active SQLAlchemy session.
    branch_id:
        Branch identifier.
    target:
        Column from ``hourly_stats`` to use as ``y``.  Typically
        ``"total_visits"`` or ``"avg_wait_minutes"``.

    Returns
    -------
    pd.DataFrame
        Columns: ``ds`` (datetime), ``y`` (float), plus regressors.
    """
    query = text(
        """
        SELECT date, hour, total_visits, avg_wait_minutes
        FROM hourly_stats
        WHERE branch_id = :bid
          AND hour >= :h_min
          AND hour < :h_max
        ORDER BY date, hour
        """
    )
    rows = db_session.execute(
        query, {"bid": branch_id, "h_min": WORKING_HOURS[0], "h_max": WORKING_HOURS[-1] + 1}
    ).fetchall()

    if not rows:
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for row in rows:
        dt = datetime.combine(row.date, datetime.min.time()).replace(hour=row.hour)
        y_value: float
        if target == "total_visits":
            y_value = float(row.total_visits)
        elif target in ("avg_wait_minutes", "avg_wait_seconds"):
            raw = row.avg_wait_minutes
            if raw is None:
                y_value = 0.0
            elif target == "avg_wait_seconds":
                y_value = float(raw) * 60.0
            else:
                y_value = float(raw)
        else:
            y_value = float(row.total_visits)
        records.append({"ds": dt, "y": y_value})

    df = pd.DataFrame(records)
    df["ds"] = pd.to_datetime(df["ds"])

    # Fill NaN targets with 0
    df["y"] = df["y"].fillna(0.0)

    # Track original (non-zero-filled) row count for MIN_DATA_POINTS checks
    original_count = len(df)

    # ---- Fill missing hourly slots with 0 ----
    # Branches may have gaps (closed early, no visitors). Prophet needs
    # a complete grid to avoid incorrect interpolation.
    all_dates = pd.date_range(df["ds"].dt.normalize().min(),
                              df["ds"].dt.normalize().max(), freq="D")
    # Skip Sundays (weekday=6) — MFC is closed
    all_dates = all_dates[all_dates.dayofweek != 6]
    full_index = pd.DatetimeIndex([
        d + pd.Timedelta(hours=h)
        for d in all_dates
        for h in WORKING_HOURS
    ])
    full_df = pd.DataFrame({"ds": full_index})
    df = full_df.merge(df, on="ds", how="left")
    df["y"] = df["y"].fillna(0.0)

    # ---- Log transform ----
    # Stabilises variance, prevents negative predictions, suits count data.
    df["y"] = np.log1p(df["y"])

    # Add regressors
    df = add_regressors(df)

    # Store original count so callers can check data sufficiency
    df.attrs["original_count"] = original_count

    return df


# ---------------------------------------------------------------------------
# Model construction helpers
# ---------------------------------------------------------------------------

def _try_cmdstanpy() -> str | None:
    """Return ``'CMDSTANPY'`` if the cmdstanpy backend is usable, else ``None``."""
    try:
        import cmdstanpy  # noqa: F401
        return "CMDSTANPY"
    except ImportError:
        return None


def _build_prophet(
    df: pd.DataFrame,
    holidays_df: pd.DataFrame | None = None,
    use_gpu: bool = False,
) -> Prophet:
    """Construct a configured :class:`Prophet` instance.

    The model uses:
    * weekly seasonality (auto)
    * yearly seasonality (enabled only when data spans >= 12 months)
    * custom *intraday* seasonality (period=1 day, fourier_order=8)
    * Russian holidays
    * regressors: ``is_month_start``, ``is_month_end``, ``is_monday``
    * GPU-accelerated MCMC via CmdStanPy OpenCL (if ``use_gpu=True``)
    """
    data_span_days = (df["ds"].max() - df["ds"].min()).days
    yearly = data_span_days >= 365

    stan_backend = _try_cmdstanpy()

    kwargs: dict[str, Any] = dict(
        yearly_seasonality=yearly,
        weekly_seasonality=True,
        daily_seasonality=False,
        changepoint_prior_scale=0.15,
        seasonality_prior_scale=1.0,
        holidays_prior_scale=1.0,
        interval_width=0.80,
    )

    if stan_backend:
        kwargs["stan_backend"] = stan_backend

    if holidays_df is not None and not holidays_df.empty:
        kwargs["holidays"] = holidays_df

    model = Prophet(**kwargs)

    # Custom intraday seasonality (period = 1 day)
    model.add_seasonality(name="intraday", period=1, fourier_order=3)

    # Regressors
    for col in REGRESSOR_COLUMNS:
        model.add_regressor(col)

    return model


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_branch_model(
    branch_id: int,
    df: pd.DataFrame,
    holidays_df: pd.DataFrame | None = None,
    use_gpu: bool = False,
) -> tuple[Prophet, Prophet]:
    """Train visits and wait-time Prophet models for a single branch.

    Parameters
    ----------
    branch_id:
        Used only for logging.
    df:
        DataFrame returned by :func:`prepare_training_data` with
        ``target="total_visits"``.  Must also contain a column
        ``y_wait`` if available (otherwise a second call to
        ``prepare_training_data`` should be made by the caller).
    holidays_df:
        Holidays DataFrame for Prophet.
    use_gpu:
        If ``True``, configure Stan OpenCL backend for GPU acceleration.

    Returns
    -------
    tuple[Prophet, Prophet]
        ``(visits_model, wait_model)``
    """
    logger.info("Training visits model for branch %d (%d rows)%s",
                branch_id, len(df), " [GPU]" if use_gpu else "")

    visits_model = _build_prophet(df, holidays_df, use_gpu=use_gpu)
    visits_model.fit(df[["ds", "y"] + REGRESSOR_COLUMNS])

    # --- Wait model ---
    # If df has y_wait column, use it.  Otherwise build a trivial model from
    # the same df with y replaced.
    wait_model = _build_prophet(df, holidays_df, use_gpu=use_gpu)

    if "y_wait" in df.columns:
        wait_df = df[["ds"] + REGRESSOR_COLUMNS].copy()
        wait_df["y"] = df["y_wait"]
    else:
        # Caller should supply a wait df; as fallback train on zeros
        wait_df = df[["ds", "y"] + REGRESSOR_COLUMNS].copy()
        wait_df["y"] = 0.0

    wait_model.fit(wait_df)

    return visits_model, wait_model


def _train_branch_worker(
    branch_id: int,
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    holidays_df: pd.DataFrame | None,
    models_dir: str,
    validate: bool,
    use_gpu: bool = False,
) -> dict[str, Any]:
    """Train a single branch in a worker process.

    This function runs in a child process via ProcessPoolExecutor.
    It trains models, saves them to disk, and returns the report dict.
    """
    # Suppress Prophet/cmdstanpy logs in worker
    logging.getLogger("prophet").setLevel(logging.WARNING)
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

    # Configure GPU in worker process if requested
    if use_gpu:
        configure_cmdstanpy_gpu(use_gpu=True)

    models_path = Path(models_dir)
    t0 = time.time()

    visits_model, wait_model = train_branch_model(branch_id, df_train, holidays_df, use_gpu=use_gpu)
    elapsed = time.time() - t0

    # Save models to disk directly from worker
    visits_path = models_path / f"branch_{branch_id}_visits.pkl"
    wait_path = models_path / f"branch_{branch_id}_wait.pkl"
    joblib.dump(visits_model, visits_path)
    joblib.dump(wait_model, wait_path)

    branch_report: dict[str, Any] = {
        "branch_id": branch_id,
        "train_rows": len(df_train),
        "training_seconds": round(elapsed, 2),
    }

    # Validation metrics
    if validate and not df_test.empty:
        metrics = validate_model(visits_model, df_test)
        branch_report["validation"] = metrics

    return branch_report


def train_all_models(
    db_session: Session,
    models_dir: str | Path,
    branch_ids: list[int] | None = None,
    validate: bool = False,
    test_split_date: str | None = None,
    n_workers: int | None = None,
    use_gpu: bool = False,
) -> dict[str, Any]:
    """Train Prophet models for all (or selected) branches and save to disk.

    Training runs in parallel across multiple CPU cores using
    ProcessPoolExecutor. Data fetching is sequential (uses DB session),
    model fitting is parallelised.

    Parameters
    ----------
    db_session:
        Active SQLAlchemy session.
    models_dir:
        Directory where ``.pkl`` files will be written.
    branch_ids:
        Restrict to these branch IDs.  ``None`` means all branches found in
        ``hourly_stats``.
    validate:
        If ``True``, perform backtesting and include metrics in the report.
    test_split_date:
        ISO date string (e.g. ``"2023-10-01"``).  Used for backtesting split.
    n_workers:
        Number of parallel worker processes.  ``None`` = ``os.cpu_count()``.
    use_gpu:
        If ``True``, configure CmdStanPy OpenCL backend for GPU-accelerated
        MCMC sampling in each worker process.

    Returns
    -------
    dict
        Training metadata / validation report.
    """
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    if n_workers is None:
        n_workers = os.cpu_count() or 4

    # Detect and configure GPU
    gpu_info = detect_gpu()
    if use_gpu and gpu_info["available"]:
        logger.info("GPU detected: %s (%d MB). GPU training enabled.",
                     gpu_info["device_name"], gpu_info["memory_mb"])
        # For GPU training, limit workers to avoid GPU memory contention
        max_gpu_workers = max(1, gpu_info.get("gpu_count", 1) * 2)
        if n_workers > max_gpu_workers:
            logger.info("Reducing workers from %d to %d for GPU memory management",
                        n_workers, max_gpu_workers)
            n_workers = max_gpu_workers
    elif use_gpu:
        logger.warning("GPU requested but not available. Falling back to CPU.")
        use_gpu = False

    # Discover branch IDs
    if branch_ids is None:
        rows = db_session.execute(
            text("SELECT DISTINCT branch_id FROM hourly_stats ORDER BY branch_id")
        ).fetchall()
        branch_ids = [r[0] for r in rows]

    logger.info("Training models for %d branches using %d workers%s",
                len(branch_ids), n_workers, " [GPU]" if use_gpu else "")

    holidays_df = get_russian_holidays_df()

    report: dict[str, Any] = {
        "trained_at": datetime.utcnow().isoformat(),
        "train_period": {},
        "num_branches_requested": len(branch_ids),
        "num_branches_trained": 0,
        "branches_skipped": [],
        "branches": [],
        "avg_training_time_seconds": 0.0,
        "n_workers": n_workers,
        "gpu_enabled": use_gpu,
        "gpu_device": gpu_info.get("device_name") if use_gpu else None,
    }

    # ---- Phase 1: Fetch data sequentially (DB session not shareable) ----
    tasks: list[tuple[int, pd.DataFrame, pd.DataFrame]] = []
    last_df_visits = pd.DataFrame()

    for idx, bid in enumerate(branch_ids, 1):
        logger.info("[%d/%d] Fetching data for branch %d", idx, len(branch_ids), bid)

        df_visits = prepare_training_data(db_session, bid, target="total_visits")
        # Use original (pre-zero-fill) count for data sufficiency check
        original_count = df_visits.attrs.get("original_count", len(df_visits))
        if df_visits.empty or original_count < MIN_DATA_POINTS:
            msg = f"Branch {bid}: insufficient data ({original_count} rows, need {MIN_DATA_POINTS})"
            logger.warning(msg)
            report["branches_skipped"].append({"branch_id": bid, "reason": msg})
            continue

        # Prepare wait data and attach as y_wait
        # NOTE: prepare_training_data already applies log1p, so y_wait is
        # already log-transformed when it comes from that function.
        df_wait = prepare_training_data(db_session, bid, target="avg_wait_minutes")
        if not df_wait.empty and len(df_wait) == len(df_visits):
            df_visits["y_wait"] = df_wait["y"].values
        else:
            df_visits["y_wait"] = 0.0

        # Backtesting split
        if validate and test_split_date:
            split_dt = pd.Timestamp(test_split_date)
            df_train = df_visits[df_visits["ds"] < split_dt].copy()
            df_test = df_visits[df_visits["ds"] >= split_dt].copy()

            if len(df_train) < MIN_DATA_POINTS:
                msg = f"Branch {bid}: not enough training data before split ({len(df_train)} rows)"
                logger.warning(msg)
                report["branches_skipped"].append({"branch_id": bid, "reason": msg})
                continue
        else:
            df_train = df_visits
            df_test = pd.DataFrame()

        tasks.append((bid, df_train, df_test))
        last_df_visits = df_visits

    logger.info("Data fetched for %d branches. Starting parallel training...", len(tasks))

    # ---- Phase 2: Train models in parallel ----
    t_total_start = time.time()
    total_time = 0.0

    # Use single process if only 1 branch or 1 worker
    if n_workers <= 1 or len(tasks) <= 1:
        for bid, df_train, df_test in tasks:
            logger.info("Training branch %d (sequential)%s", bid, " [GPU]" if use_gpu else "")
            branch_report = _train_branch_worker(
                bid, df_train, df_test, holidays_df, str(models_dir), validate,
                use_gpu=use_gpu,
            )
            total_time += branch_report["training_seconds"]
            report["branches"].append(branch_report)
            report["num_branches_trained"] += 1

            if "validation" in branch_report:
                m = branch_report["validation"]
                logger.info(
                    "  Branch %d: wMAPE=%.1f%%, MAE=%.2f, Peak=%.1f%%, CI=%.1f%%",
                    bid, m.get("mape", 0), m.get("mae", 0),
                    m.get("peak_accuracy", 0) * 100, m.get("ci_coverage", 0) * 100,
                )
            else:
                logger.info("  Branch %d: trained in %.1fs", bid, branch_report["training_seconds"])
    else:
        futures = {}
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            for bid, df_train, df_test in tasks:
                fut = pool.submit(
                    _train_branch_worker,
                    bid, df_train, df_test, holidays_df,
                    str(models_dir), validate, use_gpu,
                )
                futures[fut] = bid

            for fut in as_completed(futures):
                bid = futures[fut]
                try:
                    branch_report = fut.result()
                    total_time += branch_report["training_seconds"]
                    report["branches"].append(branch_report)
                    report["num_branches_trained"] += 1

                    if "validation" in branch_report:
                        m = branch_report["validation"]
                        logger.info(
                            "  Branch %d: wMAPE=%.1f%%, MAE=%.2f (%.1fs)",
                            bid, m.get("mape", 0), m.get("mae", 0),
                            branch_report["training_seconds"],
                        )
                    else:
                        logger.info(
                            "  Branch %d: trained in %.1fs",
                            bid, branch_report["training_seconds"],
                        )
                except Exception:
                    logger.exception("  Branch %d: training failed", bid)
                    report["branches_skipped"].append(
                        {"branch_id": bid, "reason": "Training process failed"}
                    )

    wall_time = time.time() - t_total_start

    # Summary
    n = report["num_branches_trained"]
    report["avg_training_time_seconds"] = round(total_time / max(n, 1), 2)
    report["total_training_time_seconds"] = round(total_time, 2)
    report["wall_time_seconds"] = round(wall_time, 2)
    report["speedup"] = round(total_time / max(wall_time, 0.01), 2)

    logger.info(
        "Parallel training complete: %.1fs wall time (%.1fx speedup over sequential %.1fs)",
        wall_time, report["speedup"], total_time,
    )

    if report["branches"] and not last_df_visits.empty:
        report["train_period"] = {
            "from": last_df_visits["ds"].min().isoformat(),
            "to": last_df_visits["ds"].max().isoformat(),
        }

    # Persist report
    report_path = models_dir / "training_metadata.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Report saved to %s", report_path)

    return report


# ---------------------------------------------------------------------------
# Validation / backtesting
# ---------------------------------------------------------------------------

def validate_model(model: Prophet, df_test: pd.DataFrame) -> dict[str, Any]:
    """Run backtesting on a trained Prophet *model*.

    Parameters
    ----------
    model:
        Already-fitted Prophet model.
    df_test:
        Test DataFrame with ``ds``, ``y`` and regressor columns.

    Returns
    -------
    dict
        Keys: ``mape``, ``mae``, ``rmse``, ``peak_accuracy``, ``ci_coverage``.
    """
    future = df_test[["ds"] + REGRESSOR_COLUMNS].copy()
    forecast = model.predict(future)

    # Inverse log1p transform to get back to original scale
    actual = np.maximum(np.expm1(df_test["y"].values), 0.0)
    predicted = np.maximum(np.expm1(forecast["yhat"].values), 0.0)

    mape = calculate_mape(actual, predicted)
    mae = calculate_mae(actual, predicted)
    rmse = calculate_rmse(actual, predicted)

    # Peak accuracy
    pred_df = forecast[["ds", "yhat"]].copy()
    peak_acc = calculate_peak_accuracy(df_test, pred_df, top_n=3)

    # CI coverage (inverse-transform bounds too)
    ci_lower = np.maximum(np.expm1(forecast["yhat_lower"].values), 0.0)
    ci_upper = np.maximum(np.expm1(forecast["yhat_upper"].values), 0.0)
    ci = calculate_ci_coverage(actual, ci_lower, ci_upper)

    return {
        "mape": round(mape, 2),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "peak_accuracy": round(peak_acc, 4),
        "ci_coverage": round(ci, 4),
        "test_rows": len(df_test),
    }
