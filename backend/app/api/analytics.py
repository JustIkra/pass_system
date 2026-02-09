"""API router for /api/analytics and /api/branches/compare endpoints."""

from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Branch, Forecast, HourlyStat
from app.schemas import (
    ComparisonResponse,
    ComparisonRow,
    OverloadedBranch,
    OverviewResponse,
    UnderloadedBranch,
)

router = APIRouter(tags=["analytics"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _parse_month(month: str) -> tuple[int, int]:
    if not _MONTH_RE.match(month):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid month format: '{month}'. Expected YYYY-MM.",
        )
    year, mon = month.split("-")
    return int(year), int(mon)


def _month_date_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


# ---- Compare branches ----


@router.get("/api/branches/compare", response_model=ComparisonResponse)
def compare_branches(
    ids: str = Query(..., description="Comma-separated branch IDs (2-5)"),
    month: str = Query(..., description="Month in YYYY-MM format"),
    db: Session = Depends(get_db),
) -> dict:
    """Compare 2-5 branches side by side."""
    try:
        branch_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch IDs format")

    if len(branch_ids) < 2 or len(branch_ids) > 5:
        raise HTTPException(status_code=400, detail="Provide 2-5 branch IDs")

    year, mon = _parse_month(month)
    start, end = _month_date_range(year, mon)

    rows = []
    for bid in branch_ids:
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
            avg_wait = (
                sum(f.predicted_avg_wait for f in forecasts if f.predicted_avg_wait)
                / max(1, sum(1 for f in forecasts if f.predicted_avg_wait))
            )
            hourly_visits: dict[int, float] = {}
            for f in forecasts:
                hourly_visits[f.hour] = hourly_visits.get(f.hour, 0) + f.predicted_visits
            peak_hour = max(hourly_visits, key=hourly_visits.get) if hourly_visits else None  # type: ignore[arg-type]
            overloaded = sum(1 for f in forecasts if (f.predicted_avg_wait or 0) > 20)

            avg_svc = None
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

        # Rough required windows estimate
        avg_svc_est = avg_svc if avg_svc else 15.0
        num_days = len(set(f.date for f in forecasts)) if forecasts else 1
        if num_days == 0:
            num_days = 1
        daily_visits = total_visits / num_days
        required_avg_windows = round(daily_visits * avg_svc_est / (60.0 * 12), 1)

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
            }
        )

    return {"month": month, "branches": rows}


# ---- Overview ----


@router.get("/api/analytics/overview", response_model=OverviewResponse)
def get_overview(
    month: str = Query(..., description="Month in YYYY-MM format"),
    db: Session = Depends(get_db),
) -> dict:
    """Return an overview of the entire MFC network for a given month."""
    year, mon = _parse_month(month)
    start, end = _month_date_range(year, mon)

    total_branches = db.query(func.count(Branch.id)).scalar() or 0

    # Try forecast data
    forecasts = (
        db.query(Forecast)
        .filter(Forecast.date >= start, Forecast.date < end)
        .all()
    )

    if forecasts:
        total_visits = sum(f.predicted_visits for f in forecasts)
        wait_vals = [f.predicted_avg_wait for f in forecasts if f.predicted_avg_wait]
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
                bs["wait_sum"] += f.predicted_avg_wait
                bs["wait_count"] += 1
            if (f.predicted_avg_wait or 0) > 20:
                bs["overloaded_hours"] += 1
    else:
        # Fallback to hourly_stats
        stats = (
            db.query(HourlyStat)
            .filter(HourlyStat.date >= start, HourlyStat.date < end)
            .all()
        )
        if not stats:
            stats = db.query(HourlyStat).all()

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

    # Build top overloaded and underloaded
    branch_avgs: list[tuple[int, float, int]] = []
    for bid, bs in branch_stats.items():
        avg_w = bs["wait_sum"] / bs["wait_count"] if bs["wait_count"] > 0 else 0
        branch_avgs.append((bid, avg_w, bs["overloaded_hours"]))

    # Sort by avg_wait descending for overloaded
    sorted_by_wait = sorted(branch_avgs, key=lambda x: x[1], reverse=True)

    top_overloaded = []
    for bid, avg_w, oh in sorted_by_wait[:5]:
        branch = db.get(Branch, bid)
        top_overloaded.append(
            {
                "branch_id": bid,
                "branch_name": branch.name if branch else None,
                "predicted_avg_wait": round(avg_w, 1),
                "overloaded_hours": oh,
            }
        )

    # Sort by avg_wait ascending for underloaded
    sorted_by_wait_asc = sorted(branch_avgs, key=lambda x: x[1])
    top_underloaded = []
    for bid, avg_w, oh in sorted_by_wait_asc[:5]:
        branch = db.get(Branch, bid)
        bs = branch_stats[bid]
        # rough load percent estimate
        load_pct = min(100.0, avg_w / 20.0 * 100.0) if avg_w else 0
        top_underloaded.append(
            {
                "branch_id": bid,
                "branch_name": branch.name if branch else None,
                "predicted_avg_wait": round(avg_w, 1),
                "avg_load_percent": round(load_pct, 1),
            }
        )

    return {
        "month": month,
        "total_branches": total_branches,
        "total_predicted_visits": round(total_visits, 1),
        "avg_predicted_wait": round(avg_wait, 1),
        "top_overloaded": top_overloaded,
        "top_underloaded": top_underloaded,
    }
