"""Forecast service: wraps ML model loading and prediction caching."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Branch, Forecast, HourlyStat, QueueRecord, Service

logger = logging.getLogger(__name__)

def get_forecast_data(
    db: Session, branch_id: int, from_date: date, to_date: date
) -> list[dict]:
    """Retrieve forecast data from the forecasts table for a given branch and date range."""
    rows = (
        db.query(Forecast)
        .filter(
            Forecast.branch_id == branch_id,
            Forecast.date >= from_date,
            Forecast.date <= to_date,
        )
        .order_by(Forecast.date, Forecast.hour)
        .all()
    )

    return [
        {
            "date": r.date.isoformat(),
            "hour": r.hour,
            "predicted_visits": round(r.predicted_visits, 1),
            "predicted_avg_wait": round(r.predicted_avg_wait, 1)
            if r.predicted_avg_wait is not None
            else None,
            "confidence_lower": round(r.confidence_lower, 1)
            if r.confidence_lower is not None
            else None,
            "confidence_upper": round(r.confidence_upper, 1)
            if r.confidence_upper is not None
            else None,
        }
        for r in rows
    ]


def compute_forecast_summary(data: list[dict]) -> dict:
    """Compute summary statistics from forecast data points."""
    if not data:
        return {
            "total_predicted_visits": 0,
            "peak_day": None,
            "peak_hour": None,
            "avg_daily_visits": 0,
        }

    total = sum(p["predicted_visits"] for p in data)

    # Find peak day
    daily_totals: dict[str, float] = {}
    for p in data:
        daily_totals[p["date"]] = daily_totals.get(p["date"], 0) + p["predicted_visits"]

    peak_day = max(daily_totals, key=daily_totals.get) if daily_totals else None  # type: ignore[arg-type]
    num_days = len(daily_totals) or 1

    # Find peak hour (most visits across all days)
    hourly_totals: dict[int, float] = {}
    for p in data:
        hourly_totals[p["hour"]] = hourly_totals.get(p["hour"], 0) + p["predicted_visits"]
    peak_hour = max(hourly_totals, key=hourly_totals.get) if hourly_totals else None  # type: ignore[arg-type]

    return {
        "total_predicted_visits": round(total, 1),
        "peak_day": peak_day,
        "peak_hour": peak_hour,
        "avg_daily_visits": round(total / num_days, 1),
    }


def _get_window_stats_history(
    db: Session, branch_id: int, from_date: date, to_date: date
) -> list[dict]:
    """Compute window load statistics from historical queue_records."""
    start_date = datetime(from_date.year, from_date.month, from_date.day)
    end_date = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59)

    # Check for data in the requested range; fall back to latest available data
    count_check = (
        db.query(func.count(QueueRecord.id))
        .filter(
            QueueRecord.branch_id == branch_id,
            QueueRecord.registered_at >= start_date,
            QueueRecord.registered_at <= end_date,
            QueueRecord.employee_window.isnot(None),
        )
        .scalar()
    )

    if not count_check or count_check == 0:
        # Fall back to the most recent month with data
        latest = (
            db.query(func.max(QueueRecord.registered_at))
            .filter(
                QueueRecord.branch_id == branch_id,
                QueueRecord.employee_window.isnot(None),
            )
            .scalar()
        )
        if latest is None:
            return []
        # Use the month of the latest record
        start_date = datetime(latest.year, latest.month, 1)
        if latest.month == 12:
            end_date = datetime(latest.year + 1, 1, 1)
        else:
            end_date = datetime(latest.year, latest.month + 1, 1)

    # Raw SQL — PostgreSQL syntax
    sql = """
        SELECT
            employee_window,
            CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER) as hour,
            COUNT(*) as visit_count,
            AVG(CASE WHEN service_seconds IS NOT NULL THEN service_seconds END) as avg_svc
        FROM queue_records
        WHERE branch_id = :bid
          AND registered_at >= :start
          AND registered_at < :end
          AND employee_window IS NOT NULL
        GROUP BY employee_window, CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER)
        ORDER BY employee_window, CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER)
    """
    from sqlalchemy import text

    result = db.execute(
        text(sql), {"bid": branch_id, "start": start_date, "end": end_date}
    ).fetchall()

    if not result:
        return []

    # Count working days in the period
    day_count_sql = """
        SELECT COUNT(DISTINCT CAST(registered_at AS DATE))
        FROM queue_records
        WHERE branch_id = :bid
          AND registered_at >= :start
          AND registered_at < :end
    """
    num_days = (
        db.execute(
            text(day_count_sql), {"bid": branch_id, "start": start_date, "end": end_date}
        ).scalar()
        or 1
    )

    # Get global avg service normativ
    avg_normativ_q = db.query(func.avg(Service.normativ_minutes)).filter(
        Service.normativ_minutes.isnot(None)
    )
    avg_normativ = float(avg_normativ_q.scalar() or 15.0)

    # Organize by window
    window_data: dict[str, dict[int, dict]] = {}
    for row in result:
        w = str(row[0])
        h = int(row[1])
        cnt = int(row[2])
        avg_svc = row[3]
        if w not in window_data:
            window_data[w] = {}
        window_data[w][h] = {"count": cnt, "avg_svc": avg_svc}

    windows_list = []
    for window_num in sorted(window_data.keys(), key=lambda x: (len(x), x)):
        hours_data = window_data[window_num]
        load_by_hour = []
        total_load = 0.0
        hours_counted = 0

        for hour in range(8, 20):
            hd = hours_data.get(hour, {"count": 0, "avg_svc": None})
            avg_visits = hd["count"] / num_days
            svc_min = (float(hd["avg_svc"]) / 60.0) if hd["avg_svc"] else avg_normativ
            load_pct = round((avg_visits * svc_min / 60.0) * 100.0, 1)
            load_by_hour.append(
                {
                    "hour": hour,
                    "load_percent": round(load_pct, 1),
                    "avg_visits": round(avg_visits, 1),
                }
            )
            total_load += load_pct
            hours_counted += 1

        avg_load = total_load / hours_counted if hours_counted else 0
        status = (
            "overloaded"
            if avg_load > 85
            else "normal"
            if avg_load > 50
            else "underloaded"
            if avg_load > 20
            else "idle"
        )

        windows_list.append(
            {
                "window_number": window_num,
                "avg_daily_load_percent": round(avg_load, 1),
                "load_by_hour": load_by_hour,
                "status": status,
            }
        )

    return windows_list


def _get_window_stats_forecast(
    db: Session, branch_id: int, from_date: date, to_date: date
) -> list[dict]:
    """Compute window load statistics from forecast data, distributing predicted
    visits across windows proportionally to their historical share."""
    from sqlalchemy import text

    # 1. Get forecast data for the requested period
    forecasts = (
        db.query(Forecast)
        .filter(
            Forecast.branch_id == branch_id,
            Forecast.date >= from_date,
            Forecast.date <= to_date,
        )
        .order_by(Forecast.date, Forecast.hour)
        .all()
    )

    if not forecasts:
        return []

    # 2. Get the historical window distribution from the last 30 days with data.
    #    We find the latest record date, then go back 30 days from it.
    latest_record_dt = (
        db.query(func.max(QueueRecord.registered_at))
        .filter(
            QueueRecord.branch_id == branch_id,
            QueueRecord.employee_window.isnot(None),
        )
        .scalar()
    )

    if latest_record_dt is None:
        return []

    hist_end = datetime(
        latest_record_dt.year, latest_record_dt.month, latest_record_dt.day, 23, 59, 59
    )
    hist_start = datetime(
        latest_record_dt.year, latest_record_dt.month, latest_record_dt.day
    ) - timedelta(days=30)

    distribution_sql = """
        SELECT
            employee_window,
            CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER) as hour,
            COUNT(*) as visit_count
        FROM queue_records
        WHERE branch_id = :bid
          AND registered_at >= :start
          AND registered_at <= :end
          AND employee_window IS NOT NULL
          AND CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER) >= 8
          AND CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER) < 20
        GROUP BY employee_window, CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER)
        ORDER BY employee_window, CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER)
    """

    dist_rows = db.execute(
        text(distribution_sql),
        {"bid": branch_id, "start": hist_start, "end": hist_end},
    ).fetchall()

    if not dist_rows:
        return []

    # 3. Compute per-hour total visits and per-window-per-hour share
    #    hour_totals[hour] = total visits across all windows
    #    window_hour_counts[window][hour] = visits for that window in that hour
    hour_totals: dict[int, int] = {}
    window_hour_counts: dict[str, dict[int, int]] = {}

    for row in dist_rows:
        w = str(row[0])
        h = int(row[1])
        cnt = int(row[2])
        hour_totals[h] = hour_totals.get(h, 0) + cnt
        if w not in window_hour_counts:
            window_hour_counts[w] = {}
        window_hour_counts[w][h] = cnt

    # 4. Get average service time for load calculation
    avg_normativ = (
        db.query(func.avg(Service.normativ_minutes))
        .filter(Service.normativ_minutes.isnot(None))
        .scalar()
    ) or 15.0

    # Historical avg service seconds for this branch (more accurate than normativ)
    avg_svc_seconds = (
        db.query(func.avg(HourlyStat.avg_service_seconds))
        .filter(
            HourlyStat.branch_id == branch_id,
            HourlyStat.avg_service_seconds.isnot(None),
        )
        .scalar()
    )
    avg_service_minutes = (float(avg_svc_seconds) / 60.0) if avg_svc_seconds else avg_normativ

    # 5. Aggregate forecast: average predicted_visits per hour across all days
    #    so we get a single "avg day" profile to match the historical approach
    forecast_by_hour: dict[int, list[float]] = {}
    for fc in forecasts:
        if 8 <= fc.hour < 20:
            forecast_by_hour.setdefault(fc.hour, []).append(fc.predicted_visits)

    avg_forecast_per_hour: dict[int, float] = {}
    for h, vals in forecast_by_hour.items():
        avg_forecast_per_hour[h] = sum(vals) / len(vals)

    # 6. Distribute forecast visits to windows proportionally
    all_windows = sorted(window_hour_counts.keys(), key=lambda x: (len(x), x))
    window_data: dict[str, dict[int, float]] = {w: {} for w in all_windows}

    for hour in range(8, 20):
        total_hist = hour_totals.get(hour, 0)
        avg_predicted = avg_forecast_per_hour.get(hour, 0.0)

        for w in all_windows:
            w_hist = window_hour_counts[w].get(hour, 0)
            if total_hist > 0:
                share = w_hist / total_hist
            else:
                # Uniform distribution if no historical data for this hour
                share = 1.0 / len(all_windows) if all_windows else 0.0
            window_data[w][hour] = avg_predicted * share

    # 7. Build result list
    windows_list = []
    for window_num in all_windows:
        load_by_hour = []
        total_load = 0.0
        hours_counted = 0

        for hour in range(8, 20):
            predicted_visits = window_data[window_num].get(hour, 0.0)
            load_pct = round((predicted_visits * avg_service_minutes / 60.0) * 100.0, 1)
            load_by_hour.append(
                {
                    "hour": hour,
                    "load_percent": round(load_pct, 1),
                    "avg_visits": round(predicted_visits, 1),
                }
            )
            total_load += load_pct
            hours_counted += 1

        avg_load = total_load / hours_counted if hours_counted else 0
        status = (
            "overloaded"
            if avg_load > 85
            else "normal"
            if avg_load > 50
            else "underloaded"
            if avg_load > 20
            else "idle"
        )

        windows_list.append(
            {
                "window_number": window_num,
                "avg_daily_load_percent": round(avg_load, 1),
                "load_by_hour": load_by_hour,
                "status": status,
            }
        )

    return windows_list


def get_window_stats(
    db: Session, branch_id: int, from_date: date, to_date: date
) -> tuple[list[dict], str]:
    """Compute window load statistics.

    If *from_date* is today or in the future -- use forecast data
    distributed across windows proportionally to their historical share.
    Otherwise use the existing historical queue_records logic.

    Returns
    -------
    tuple[list[dict], str]
        (windows_list, data_source) where data_source is "forecast" or "history".
    """
    today = date.today()

    if from_date >= today:
        windows = _get_window_stats_forecast(db, branch_id, from_date, to_date)
        return windows, "forecast"

    windows = _get_window_stats_history(db, branch_id, from_date, to_date)
    return windows, "history"


# Module-level cache for validation report
_validation_cache: dict | None = None


def _load_validation_report() -> dict:
    """Load and cache validation_report.json, indexed by branch_id."""
    global _validation_cache
    if _validation_cache is not None:
        return _validation_cache

    from app.config import settings
    import json

    report_path = Path(settings.MODELS_DIR) / "validation_report.json"
    if not report_path.exists():
        _validation_cache = {}
        return _validation_cache

    with open(report_path) as f:
        data = json.load(f)

    _validation_cache = {}
    for b in data.get("branches", []):
        _validation_cache[b["branch_id"]] = b
    return _validation_cache


def get_valid_branch_ids() -> set[int]:
    """Return set of branch IDs that have validated models."""
    return set(_load_validation_report().keys())


def _load_training_metadata() -> dict:
    """Load training_metadata.json for trained_at timestamp."""
    from app.config import settings
    import json

    meta_path = Path(settings.MODELS_DIR) / "training_metadata.json"
    if not meta_path.exists():
        return {}

    with open(meta_path) as f:
        return json.load(f)


def get_quality_metrics(db: Session, branch_id: int) -> dict | None:
    """
    Возвращает метрики качества прогноза для филиала.

    Reads real validation metrics from validation_report.json instead of
    hardcoded values. Returns None if branch has no trained model.
    """
    report = _load_validation_report()
    branch_metrics = report.get(branch_id)

    if branch_metrics is None:
        return None

    wmape = branch_metrics["mape_daily"]
    ci_coverage_pct = round(branch_metrics.get("ci_coverage", 0) * 100, 1)

    # Combine CI coverage with wMAPE for honest confidence score.
    # Pure CI coverage is misleading when Prophet widens intervals for bad models.
    wmape_score = max(0.0, 100.0 - wmape)
    confidence = round(0.5 * ci_coverage_pct + 0.5 * wmape_score, 1)

    # Training days from DB (real data)
    days_count = (
        db.query(func.count(func.distinct(HourlyStat.date)))
        .filter(HourlyStat.branch_id == branch_id)
        .scalar()
    ) or 0

    # trained_at from training_metadata.json
    training_meta = _load_training_metadata()
    last_updated = training_meta.get("trained_at", "")

    # Recommendations based on actual wMAPE
    recommendations = None
    if wmape >= 25:
        recommendations = [
            "Используйте прогноз как ориентир, не как точное значение",
            "Проверяйте фактические данные чаще (ежедневно вместо еженедельно)",
        ]
        if wmape >= 50:
            recommendations.append(
                "Модель требует дополнительных данных или переобучения"
            )

    return {
        'wMAPE': round(wmape, 1),
        'confidence': confidence,
        'training_days': int(days_count),
        'last_updated': last_updated,
        'recommendations': recommendations,
    }


def get_staffing_recommendations(
    db: Session, branch_id: int, from_date: date, to_date: date
) -> list[dict]:
    """Compute staffing recommendations based on forecast data and service norms."""
    forecast_data = get_forecast_data(db, branch_id, from_date, to_date)

    # Get average service time from norms
    avg_normativ_q = db.query(func.avg(Service.normativ_minutes)).filter(
        Service.normativ_minutes.isnot(None)
    )
    avg_normativ = float(avg_normativ_q.scalar() or 15.0)

    # Get historical average windows active for this branch
    avg_windows = (
        db.query(func.avg(HourlyStat.num_windows_active))
        .filter(
            HourlyStat.branch_id == branch_id,
            HourlyStat.num_windows_active > 0,
        )
        .scalar()
    )
    current_windows_avg = int(round(avg_windows)) if avg_windows else 1

    # Also get historical avg service seconds for the branch
    avg_svc = (
        db.query(func.avg(HourlyStat.avg_service_seconds))
        .filter(
            HourlyStat.branch_id == branch_id,
            HourlyStat.avg_service_seconds.isnot(None),
        )
        .scalar()
    )
    avg_service_minutes = (float(avg_svc) / 60.0) if avg_svc else avg_normativ

    recommendations = []
    for point in forecast_data:
        pv = point["predicted_visits"]
        required = max(1, math.ceil(pv * avg_service_minutes / 60.0))
        delta = required - current_windows_avg
        status = (
            "understaffed"
            if delta > 0
            else "overstaffed"
            if delta < 0
            else "optimal"
        )
        recommendations.append(
            {
                "date": point["date"],
                "hour": point["hour"],
                "predicted_visits": round(pv, 1),
                "avg_service_minutes": round(avg_service_minutes, 1),
                "required_windows": required,
                "current_windows_avg": current_windows_avg,
                "delta": delta,
                "status": status,
            }
        )

    return recommendations
