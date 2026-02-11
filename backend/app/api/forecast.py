"""API router for forecast, windows and staffing endpoints."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Optional

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
    get_quality_metrics,
    get_staffing_recommendations,
    get_window_stats,
)

router = APIRouter(prefix="/api/branches", tags=["forecast"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")

_MAX_DATE_RANGE_DAYS = 60


def _parse_month(month: str) -> tuple[int, int]:
    """Validate and parse YYYY-MM string. Raises 422 on bad format."""
    if not _MONTH_RE.match(month):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid month format: '{month}'. Expected YYYY-MM.",
        )
    year, mon = month.split("-")
    return int(year), int(mon)


def _parse_date(value: str, param_name: str) -> date:
    """Validate and parse YYYY-MM-DD string into a date object."""
    if not _DATE_RE.match(value):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {param_name} format: '{value}'. Expected YYYY-MM-DD.",
        )
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {param_name} date: '{value}'.",
        )


def _resolve_date_range(
    from_date: Optional[str],
    to_date: Optional[str],
    month: Optional[str],
) -> tuple[date, date]:
    """Resolve date range from query parameters.

    Priority:
    1. from_date / to_date  -- explicit date range
    2. month                -- first/last day of the month
    3. default              -- today + 30 days
    """
    if from_date is not None:
        fd = _parse_date(from_date, "from_date")
        if to_date is not None:
            td = _parse_date(to_date, "to_date")
        else:
            # Default to_date: from_date + 30 days
            td = fd + timedelta(days=30)
        if td < fd:
            raise HTTPException(
                status_code=422,
                detail="to_date must not be earlier than from_date.",
            )
        if (td - fd).days > _MAX_DATE_RANGE_DAYS:
            raise HTTPException(
                status_code=422,
                detail=f"Date range must not exceed {_MAX_DATE_RANGE_DAYS} days.",
            )
        return fd, td

    if month is not None:
        year, mon = _parse_month(month)
        fd = date(year, mon, 1)
        last_day = calendar.monthrange(year, mon)[1]
        td = date(year, mon, last_day)
        return fd, td

    # Default: today + 30 days
    fd = date.today()
    td = fd + timedelta(days=30)
    return fd, td


def _ensure_branch(db: Session, branch_id: int) -> Branch:
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return branch


# ---- Forecast ----


@router.get("/{branch_id}/forecast", response_model=ForecastResponse)
def get_forecast(
    branch_id: int,
    month: Optional[str] = Query(None, description="Month in YYYY-MM format (backward compat)"),
    from_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> dict:
    """Return forecast data for a branch for the given date range or month."""
    fd, td = _resolve_date_range(from_date, to_date, month)
    branch = _ensure_branch(db, branch_id)

    data = get_forecast_data(db, branch_id, fd, td)
    summary = compute_forecast_summary(data)
    quality = get_quality_metrics(db, branch_id)

    return {
        "branch_id": branch.id,
        "branch_name": branch.name,
        "from_date": fd.isoformat(),
        "to_date": td.isoformat(),
        "data": data,
        "summary": summary,
        "quality_metrics": quality,
    }


# ---- Windows ----


@router.get("/{branch_id}/windows", response_model=WindowsResponse)
def get_windows(
    branch_id: int,
    month: Optional[str] = Query(None, description="Month in YYYY-MM format (backward compat)"),
    from_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> dict:
    """Return window load data for a branch."""
    fd, td = _resolve_date_range(from_date, to_date, month)
    _ensure_branch(db, branch_id)

    windows, data_source = get_window_stats(db, branch_id, fd, td)
    return {
        "branch_id": branch_id,
        "from_date": fd.isoformat(),
        "to_date": td.isoformat(),
        "windows": windows,
        "data_source": data_source,
    }


# ---- Staffing ----


@router.get("/{branch_id}/staffing", response_model=StaffingResponse)
def get_staffing(
    branch_id: int,
    month: Optional[str] = Query(None, description="Month in YYYY-MM format (backward compat)"),
    from_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> dict:
    """Return staffing recommendations for a branch."""
    fd, td = _resolve_date_range(from_date, to_date, month)
    _ensure_branch(db, branch_id)

    recommendations = get_staffing_recommendations(db, branch_id, fd, td)
    return {
        "branch_id": branch_id,
        "from_date": fd.isoformat(),
        "to_date": td.isoformat(),
        "recommendations": recommendations,
    }


# ---- History ----


@router.get("/{branch_id}/history", response_model=HistoryResponse)
def get_history(
    branch_id: int,
    from_month: Optional[str] = Query(None, alias="from", description="Start month YYYY-MM (backward compat)"),
    to_month: Optional[str] = Query(None, alias="to", description="End month YYYY-MM (backward compat)"),
    from_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> dict:
    """Return historical hourly_stats data for a branch over a date range."""
    _ensure_branch(db, branch_id)

    # Resolve date range: prefer from_date/to_date, then from/to months, then default
    if from_date is not None:
        fd, td = _resolve_date_range(from_date, to_date, None)
    elif from_month is not None and to_month is not None:
        from_year, from_mon = _parse_month(from_month)
        to_year, to_mon = _parse_month(to_month)
        fd = date(from_year, from_mon, 1)
        last_day = calendar.monthrange(to_year, to_mon)[1]
        td = date(to_year, to_mon, last_day)
    else:
        # Default: last 30 days of history
        td = date.today()
        fd = td - timedelta(days=30)

    hourly_rows = (
        db.query(HourlyStat)
        .filter(
            HourlyStat.branch_id == branch_id,
            HourlyStat.date >= fd,
            HourlyStat.date <= td,
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
        "period": {"from_date": fd.isoformat(), "to_date": td.isoformat()},
        "daily": daily,
        "hourly": hourly,
    }
