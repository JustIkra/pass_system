"""API router for forecast, windows and staffing endpoints."""

from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Branch, Forecast, HourlyStat, QueueRecord
from app.schemas import (
    ForecastPoint,
    ForecastResponse,
    ForecastSummary,
    HistoryResponse,
    DateRange,
    DailyHistory,
    HourlyHistory,
    StaffingRecommendation,
    StaffingResponse,
    WindowLoad,
    WindowsResponse,
)
from app.services.forecast_service import (
    compute_forecast_summary,
    get_forecast_data,
    get_staffing_recommendations,
    get_window_stats,
)

router = APIRouter(prefix="/api/branches", tags=["forecast"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _parse_month(month: str) -> tuple[int, int]:
    """Validate and parse YYYY-MM string. Raises 422 on bad format."""
    if not _MONTH_RE.match(month):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid month format: '{month}'. Expected YYYY-MM.",
        )
    year, mon = month.split("-")
    return int(year), int(mon)


def _ensure_branch(db: Session, branch_id: int) -> Branch:
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return branch


# ---- Forecast ----


@router.get("/{branch_id}/forecast", response_model=ForecastResponse)
def get_forecast(
    branch_id: int,
    month: str = Query(..., description="Month in YYYY-MM format"),
    db: Session = Depends(get_db),
) -> dict:
    """Return forecast data for a branch for the given month."""
    year, mon = _parse_month(month)
    branch = _ensure_branch(db, branch_id)

    data = get_forecast_data(db, branch_id, year, mon)
    summary = compute_forecast_summary(data)

    return {
        "branch_id": branch.id,
        "branch_name": branch.name,
        "month": month,
        "data": data,
        "summary": summary,
    }


# ---- Windows ----


@router.get("/{branch_id}/windows", response_model=WindowsResponse)
def get_windows(
    branch_id: int,
    month: str = Query(..., description="Month in YYYY-MM format"),
    db: Session = Depends(get_db),
) -> dict:
    """Return window load data for a branch."""
    year, mon = _parse_month(month)
    _ensure_branch(db, branch_id)

    windows = get_window_stats(db, branch_id, year, mon)
    return {
        "branch_id": branch_id,
        "month": month,
        "windows": windows,
    }


# ---- Staffing ----


@router.get("/{branch_id}/staffing", response_model=StaffingResponse)
def get_staffing(
    branch_id: int,
    month: str = Query(..., description="Month in YYYY-MM format"),
    db: Session = Depends(get_db),
) -> dict:
    """Return staffing recommendations for a branch."""
    year, mon = _parse_month(month)
    _ensure_branch(db, branch_id)

    recommendations = get_staffing_recommendations(db, branch_id, year, mon)
    return {
        "branch_id": branch_id,
        "month": month,
        "recommendations": recommendations,
    }


# ---- History ----


@router.get("/{branch_id}/history", response_model=HistoryResponse)
def get_history(
    branch_id: int,
    from_month: str = Query(..., alias="from", description="Start month YYYY-MM"),
    to_month: str = Query(..., alias="to", description="End month YYYY-MM"),
    db: Session = Depends(get_db),
) -> dict:
    """Return historical hourly_stats data for a branch over a date range."""
    from_year, from_mon = _parse_month(from_month)
    to_year, to_mon = _parse_month(to_month)
    _ensure_branch(db, branch_id)

    start_date = date(from_year, from_mon, 1)
    if to_mon == 12:
        end_date = date(to_year + 1, 1, 1)
    else:
        end_date = date(to_year, to_mon + 1, 1)

    hourly_rows = (
        db.query(HourlyStat)
        .filter(
            HourlyStat.branch_id == branch_id,
            HourlyStat.date >= start_date,
            HourlyStat.date < end_date,
        )
        .order_by(HourlyStat.date, HourlyStat.hour)
        .all()
    )

    # Aggregate daily
    daily_map: dict[str, dict] = {}
    for row in hourly_rows:
        d = row.date.isoformat()
        if d not in daily_map:
            daily_map[d] = {
                "date": d,
                "total_visits": 0,
                "wait_sum": 0.0,
                "wait_count": 0,
                "svc_sum": 0.0,
                "svc_count": 0,
                "peak_hour": None,
                "peak_visits": 0,
            }
        dm = daily_map[d]
        dm["total_visits"] += row.total_visits
        if row.avg_wait_seconds is not None:
            dm["wait_sum"] += row.avg_wait_seconds * row.total_visits
            dm["wait_count"] += row.total_visits
        if row.avg_service_seconds is not None:
            dm["svc_sum"] += row.avg_service_seconds * row.total_visits
            dm["svc_count"] += row.total_visits
        if row.total_visits > dm["peak_visits"]:
            dm["peak_visits"] = row.total_visits
            dm["peak_hour"] = row.hour

    daily = []
    for d_data in daily_map.values():
        avg_wait = (
            round(d_data["wait_sum"] / d_data["wait_count"] / 60.0, 1)
            if d_data["wait_count"] > 0
            else None
        )
        avg_svc = (
            round(d_data["svc_sum"] / d_data["svc_count"] / 60.0, 1)
            if d_data["svc_count"] > 0
            else None
        )
        daily.append(
            {
                "date": d_data["date"],
                "total_visits": d_data["total_visits"],
                "avg_wait_minutes": avg_wait,
                "avg_service_minutes": avg_svc,
                "peak_hour": d_data["peak_hour"],
            }
        )

    hourly = [
        {
            "date": r.date.isoformat(),
            "hour": r.hour,
            "total_visits": r.total_visits,
            "avg_wait_minutes": round(r.avg_wait_seconds / 60.0, 1)
            if r.avg_wait_seconds is not None
            else None,
            "avg_service_minutes": round(r.avg_service_seconds / 60.0, 1)
            if r.avg_service_seconds is not None
            else None,
            "num_windows_active": r.num_windows_active,
        }
        for r in hourly_rows
    ]

    return {
        "branch_id": branch_id,
        "period": {"from_date": from_month, "to_date": to_month},
        "daily": daily,
        "hourly": hourly,
    }
