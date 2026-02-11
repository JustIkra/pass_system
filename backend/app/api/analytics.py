"""API router for /api/analytics and /api/branches/compare endpoints."""

from __future__ import annotations

import calendar
import math
import re
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Branch, Forecast, HourlyStat
from app.services.forecast_service import get_valid_branch_ids
from app.schemas import (
    ComparisonResponse,
    ComparisonRow,
    OverloadedBranch,
    OverviewResponse,
    UnderloadedBranch,
)

router = APIRouter(tags=["analytics"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")

_MAX_DATE_RANGE_DAYS = 60


def _parse_month(month: str) -> tuple[int, int]:
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


def _get_branch_avg_service_minutes(db: Session, branch_id: int) -> float:
    """Get median avg_service_seconds from hourly_stats for a branch, convert to minutes.

    Uses the percentile approach: fetch all non-null values, take the median.
    Fallback: 15.0 minutes.
    """
    rows = (
        db.query(HourlyStat.avg_service_seconds)
        .filter(
            HourlyStat.branch_id == branch_id,
            HourlyStat.avg_service_seconds.isnot(None),
            HourlyStat.avg_service_seconds > 0,
        )
        .order_by(HourlyStat.avg_service_seconds)
        .all()
    )
    if not rows:
        return 15.0
    values = [float(r[0]) for r in rows]
    n = len(values)
    if n % 2 == 1:
        median_sec = values[n // 2]
    else:
        median_sec = (values[n // 2 - 1] + values[n // 2]) / 2.0
    return median_sec / 60.0


def _compute_required_avg_windows_from_hourly(
    hourly_visits_per_slot: dict[tuple, float],
    avg_svc_minutes: float,
) -> float:
    """Compute required_avg_windows from per-(date, hour) predicted visits.

    For each (date, hour) slot: required = ceil(visits * avg_svc_minutes / 60).
    Return the average across all slots, rounded to 1 decimal.
    """
    if not hourly_visits_per_slot:
        return 0.0
    total_required = 0.0
    count = 0
    for _key, visits in hourly_visits_per_slot.items():
        required = math.ceil(visits * avg_svc_minutes / 60.0)
        total_required += required
        count += 1
    if count == 0:
        return 0.0
    return round(total_required / count, 1)


# ---- Compare branches ----


@router.get("/api/branches/compare", response_model=ComparisonResponse)
def compare_branches(
    ids: str = Query(..., description="Comma-separated branch IDs (2-5)"),
    month: Optional[str] = Query(None, description="Month in YYYY-MM format (backward compat)"),
    from_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> dict:
    """Compare 2-5 branches side by side."""
    try:
        branch_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch IDs format")

    if len(branch_ids) < 2 or len(branch_ids) > 5:
        raise HTTPException(status_code=400, detail="Provide 2-5 branch IDs")

    fd, td = _resolve_date_range(from_date, to_date, month)
    start = fd
    end = td + timedelta(days=1)  # exclusive upper bound for < comparisons

    valid_ids = get_valid_branch_ids()
    rows = []
    for bid in branch_ids:
        if bid not in valid_ids:
            continue
        branch = db.get(Branch, bid)
        if not branch:
            continue

        # Try forecast data first
        forecasts = (
            db.query(Forecast)
            .filter(
                Forecast.branch_id == bid,
                Forecast.date >= start,
                Forecast.date < end,
            )
            .all()
        )

        if forecasts:
            total_visits = sum(f.predicted_visits for f in forecasts)
            wait_vals_f = [
                f.predicted_avg_wait
                for f in forecasts if f.predicted_avg_wait is not None
            ]
            avg_wait = (sum(wait_vals_f) / len(wait_vals_f)) if wait_vals_f else 0
            hourly_visits: dict[int, float] = {}
            for f in forecasts:
                hourly_visits[f.hour] = hourly_visits.get(f.hour, 0) + f.predicted_visits
            peak_hour = max(hourly_visits, key=hourly_visits.get) if hourly_visits else None  # type: ignore[arg-type]
            overloaded = sum(
                1 for f in forecasts
                if (f.predicted_avg_wait or 0) > 20
            )

            # Get avg_service from historical hourly_stats (median, in minutes)
            avg_svc = _get_branch_avg_service_minutes(db, bid)

            # Compute required_avg_windows from per-(date, hour) forecast slots
            hourly_slots: dict[tuple, float] = {}
            for f in forecasts:
                hourly_slots[(f.date, f.hour)] = f.predicted_visits
            avg_svc_est = avg_svc if avg_svc else 15.0
            required_avg_windows = _compute_required_avg_windows_from_hourly(
                hourly_slots, avg_svc_est
            )

            # Compute load_percent from required_avg_windows vs avg available windows
            avg_windows_available_row = (
                db.query(func.avg(HourlyStat.num_windows_active))
                .filter(
                    HourlyStat.branch_id == bid,
                    HourlyStat.num_windows_active > 0,
                )
                .scalar()
            )
            avg_windows_available = float(avg_windows_available_row) if avg_windows_available_row else 0.0
            if avg_windows_available > 0:
                load_percent = min(150.0, (required_avg_windows / avg_windows_available) * 100)
            else:
                load_percent = 0.0
        else:
            # Fallback to historical hourly_stats
            stats = (
                db.query(HourlyStat)
                .filter(
                    HourlyStat.branch_id == bid,
                    HourlyStat.date >= start,
                    HourlyStat.date < end,
                )
                .all()
            )
            if not stats:
                # Try all historical data
                stats = (
                    db.query(HourlyStat)
                    .filter(HourlyStat.branch_id == bid)
                    .all()
                )

            total_visits = sum(s.total_visits for s in stats)
            wait_vals = [s.avg_wait_seconds for s in stats if s.avg_wait_seconds]
            avg_wait = (sum(wait_vals) / len(wait_vals) / 60.0) if wait_vals else 0
            svc_vals = [s.avg_service_seconds for s in stats if s.avg_service_seconds]
            avg_svc = (sum(svc_vals) / len(svc_vals) / 60.0) if svc_vals else None

            hourly_visits_h: dict[int, int] = {}
            for s in stats:
                hourly_visits_h[s.hour] = hourly_visits_h.get(s.hour, 0) + s.total_visits
            peak_hour = max(hourly_visits_h, key=hourly_visits_h.get) if hourly_visits_h else None  # type: ignore[arg-type]
            overloaded = sum(
                1 for s in stats if s.avg_wait_seconds and s.avg_wait_seconds / 60.0 > 20
            )

            # Compute required_avg_windows from per-(date, hour) historical slots
            avg_svc_est = avg_svc if avg_svc else 15.0
            hourly_slots_h: dict[tuple, float] = {}
            for s in stats:
                hourly_slots_h[(s.date, s.hour)] = s.total_visits
            required_avg_windows = _compute_required_avg_windows_from_hourly(
                hourly_slots_h, avg_svc_est
            )

            # Compute load_percent from required_avg_windows vs avg available windows
            windows_vals = [s.num_windows_active for s in stats if s.num_windows_active and s.num_windows_active > 0]
            avg_windows_available = sum(windows_vals) / len(windows_vals) if windows_vals else 0.0
            if avg_windows_available > 0:
                load_percent = min(150.0, (required_avg_windows / avg_windows_available) * 100)
            else:
                load_percent = 0.0

        rows.append(
            {
                "id": bid,
                "name": branch.name,
                "predicted_total_visits": round(total_visits, 1),
                "predicted_avg_wait": round(avg_wait, 1) if avg_wait else None,
                "predicted_avg_service": round(avg_svc, 1) if avg_svc else None,
                "predicted_peak_hour": peak_hour,
                "required_avg_windows": required_avg_windows,
                "overloaded_hours_count": overloaded,
                "load_percent": round(load_percent, 1),
            }
        )

    return {"from_date": fd.isoformat(), "to_date": td.isoformat(), "branches": rows}


# ---- Overview ----


@router.get("/api/analytics/overview", response_model=OverviewResponse)
def get_overview(
    month: Optional[str] = Query(None, description="Month in YYYY-MM format (backward compat)"),
    from_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> dict:
    """Return an overview of the entire MFC network for a given date range."""
    fd, td = _resolve_date_range(from_date, to_date, month)
    start = fd
    end = td + timedelta(days=1)  # exclusive upper bound for < comparisons

    valid_ids = get_valid_branch_ids()
    total_branches = len(valid_ids) if valid_ids else 0

    # Try forecast data (only validated branches)
    q = db.query(Forecast).filter(Forecast.date >= start, Forecast.date < end)
    if valid_ids:
        q = q.filter(Forecast.branch_id.in_(valid_ids))
    forecasts = q.all()

    if forecasts:
        total_visits = sum(f.predicted_visits for f in forecasts)
        wait_vals = [
            f.predicted_avg_wait
            for f in forecasts if f.predicted_avg_wait is not None
        ]
        avg_wait = (sum(wait_vals) / len(wait_vals)) if wait_vals else 0

        # Per-branch aggregation
        branch_stats: dict[int, dict] = {}
        for f in forecasts:
            if f.branch_id not in branch_stats:
                branch_stats[f.branch_id] = {
                    "total_visits": 0,
                    "wait_sum": 0.0,
                    "wait_count": 0,
                    "overloaded_hours": 0,
                }
            bs = branch_stats[f.branch_id]
            bs["total_visits"] += f.predicted_visits
            if f.predicted_avg_wait is not None:
                clamped_wait = f.predicted_avg_wait
                bs["wait_sum"] += clamped_wait
                bs["wait_count"] += 1
            if (f.predicted_avg_wait or 0) > 20:
                bs["overloaded_hours"] += 1
    else:
        # Fallback to hourly_stats (only validated branches)
        q = db.query(HourlyStat).filter(HourlyStat.date >= start, HourlyStat.date < end)
        if valid_ids:
            q = q.filter(HourlyStat.branch_id.in_(valid_ids))
        stats = q.all()
        if not stats:
            q2 = db.query(HourlyStat)
            if valid_ids:
                q2 = q2.filter(HourlyStat.branch_id.in_(valid_ids))
            stats = q2.all()

        total_visits = sum(s.total_visits for s in stats)
        wait_vals_h = [s.avg_wait_seconds / 60.0 for s in stats if s.avg_wait_seconds]
        avg_wait = (sum(wait_vals_h) / len(wait_vals_h)) if wait_vals_h else 0

        branch_stats = {}
        for s in stats:
            if s.branch_id not in branch_stats:
                branch_stats[s.branch_id] = {
                    "total_visits": 0,
                    "wait_sum": 0.0,
                    "wait_count": 0,
                    "overloaded_hours": 0,
                }
            bs = branch_stats[s.branch_id]
            bs["total_visits"] += s.total_visits
            if s.avg_wait_seconds:
                bs["wait_sum"] += s.avg_wait_seconds / 60.0
                bs["wait_count"] += 1
            if s.avg_wait_seconds and s.avg_wait_seconds / 60.0 > 20:
                bs["overloaded_hours"] += 1

    # Build top overloaded and underloaded with real thresholds
    branch_avgs: list[tuple[int, float, int, float]] = []
    for bid, bs in branch_stats.items():
        avg_w = bs["wait_sum"] / bs["wait_count"] if bs["wait_count"] > 0 else 0
        load_pct = min(100.0, avg_w / 20.0 * 100.0) if avg_w else 0
        branch_avgs.append((bid, avg_w, bs["overloaded_hours"], load_pct))

    # Overloaded: only branches where avg wait > 20 min
    overloaded = [
        (bid, avg_w, oh, lp)
        for bid, avg_w, oh, lp in branch_avgs
        if avg_w > 20
    ]
    overloaded.sort(key=lambda x: x[1], reverse=True)

    top_overloaded = []
    for bid, avg_w, oh, _lp in overloaded[:5]:
        branch = db.get(Branch, bid)
        top_overloaded.append(
            {
                "branch_id": bid,
                "branch_name": branch.name if branch else None,
                "predicted_avg_wait": round(avg_w, 1),
                "overloaded_hours": oh,
            }
        )

    # Underloaded: only branches where load < 30%
    underloaded = [
        (bid, avg_w, oh, lp)
        for bid, avg_w, oh, lp in branch_avgs
        if lp < 30
    ]
    underloaded.sort(key=lambda x: x[3])

    top_underloaded = []
    for bid, avg_w, _oh, lp in underloaded[:5]:
        branch = db.get(Branch, bid)
        top_underloaded.append(
            {
                "branch_id": bid,
                "branch_name": branch.name if branch else None,
                "predicted_avg_wait": round(avg_w, 1),
                "avg_load_percent": round(lp, 1),
            }
        )

    return {
        "from_date": fd.isoformat(),
        "to_date": td.isoformat(),
        "total_branches": total_branches,
        "total_predicted_visits": round(total_visits, 1),
        "avg_predicted_wait": round(avg_wait, 1),
        "top_overloaded": top_overloaded,
        "top_underloaded": top_underloaded,
    }
