"""Forecast service: wraps ML model loading and prediction caching."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Branch, Forecast, HourlyStat, QueueRecord, Service

logger = logging.getLogger(__name__)


def get_forecast_data(
    db: Session, branch_id: int, year: int, month: int
) -> list[dict]:
    """Retrieve forecast data from the forecasts table for a given branch and month."""
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    rows = (
        db.query(Forecast)
        .filter(
            Forecast.branch_id == branch_id,
            Forecast.date >= start_date,
            Forecast.date < end_date,
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


def get_window_stats(
    db: Session, branch_id: int, year: int, month: int
) -> list[dict]:
    """Compute window load statistics from historical queue_records."""
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    # Check for data in the requested month; fall back to latest available data
    count_check = (
        db.query(func.count(QueueRecord.id))
        .filter(
            QueueRecord.branch_id == branch_id,
            QueueRecord.registered_at >= start_date,
            QueueRecord.registered_at < end_date,
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
    avg_normativ = avg_normativ_q.scalar() or 15.0

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
            svc_min = (hd["avg_svc"] / 60.0) if hd["avg_svc"] else avg_normativ
            load_pct = min(100.0, (avg_visits * svc_min / 60.0) * 100.0)
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


def get_staffing_recommendations(
    db: Session, branch_id: int, year: int, month: int
) -> list[dict]:
    """Compute staffing recommendations based on forecast data and service norms."""
    forecast_data = get_forecast_data(db, branch_id, year, month)

    # Get average service time from norms
    avg_normativ_q = db.query(func.avg(Service.normativ_minutes)).filter(
        Service.normativ_minutes.isnot(None)
    )
    avg_normativ = avg_normativ_q.scalar() or 15.0

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
    avg_service_minutes = (avg_svc / 60.0) if avg_svc else avg_normativ

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
