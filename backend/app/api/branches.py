"""API router for /api/branches endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Branch, Employee, HourlyStat, QueueRecord
from app.schemas import (
    BranchDetail,
    BranchListItem,
    DateRange,
    ServiceStat,
)

router = APIRouter(prefix="/api/branches", tags=["branches"])


@router.get("", response_model=list[BranchListItem])
def list_branches(db: Session = Depends(get_db)) -> list[dict]:
    """Return a list of all branches with summary stats."""
    branches = db.query(Branch).order_by(Branch.id).all()
    result = []
    for b in branches:
        # Get total records and date range
        stats = (
            db.query(
                func.count(QueueRecord.id),
                func.min(QueueRecord.registered_at),
                func.max(QueueRecord.registered_at),
            )
            .filter(QueueRecord.branch_id == b.id)
            .first()
        )
        total_records = stats[0] if stats else 0
        from_date = stats[1].strftime("%Y-%m-%d") if stats and stats[1] else None
        to_date = stats[2].strftime("%Y-%m-%d") if stats and stats[2] else None

        result.append(
            {
                "id": b.id,
                "name": b.name,
                "depart_name_mfc": b.depart_name_mfc,
                "total_records": total_records,
                "date_range": {"from_date": from_date, "to_date": to_date},
            }
        )
    return result


@router.get("/{branch_id}", response_model=BranchDetail)
def get_branch(branch_id: int, db: Session = Depends(get_db)) -> dict:
    """Return detailed information about a single branch."""
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    total_records = (
        db.query(func.count(QueueRecord.id))
        .filter(QueueRecord.branch_id == branch_id)
        .scalar()
        or 0
    )

    num_employees = (
        db.query(func.count(Employee.id))
        .filter(Employee.branch_id == branch_id)
        .scalar()
        or 0
    )

    # Number of distinct windows
    num_windows = (
        db.query(func.count(func.distinct(QueueRecord.employee_window)))
        .filter(
            QueueRecord.branch_id == branch_id,
            QueueRecord.employee_window.isnot(None),
        )
        .scalar()
        or 0
    )

    # Average daily visits
    num_days = (
        db.query(func.count(func.distinct(func.date(QueueRecord.registered_at))))
        .filter(QueueRecord.branch_id == branch_id)
        .scalar()
        or 1
    )
    avg_daily_visits = round(total_records / num_days, 1) if num_days else 0

    # Average wait and service time
    avg_wait_sec = (
        db.query(func.avg(QueueRecord.wait_seconds))
        .filter(
            QueueRecord.branch_id == branch_id,
            QueueRecord.wait_seconds.isnot(None),
        )
        .scalar()
    )
    avg_wait_minutes = round(avg_wait_sec / 60.0, 1) if avg_wait_sec else 0

    avg_svc_sec = (
        db.query(func.avg(QueueRecord.service_seconds))
        .filter(
            QueueRecord.branch_id == branch_id,
            QueueRecord.service_seconds.isnot(None),
        )
        .scalar()
    )
    avg_service_minutes = round(avg_svc_sec / 60.0, 1) if avg_svc_sec else 0

    # Top services
    top_services_rows = (
        db.query(
            QueueRecord.service_id,
            QueueRecord.service_name,
            func.count(QueueRecord.id).label("cnt"),
        )
        .filter(
            QueueRecord.branch_id == branch_id,
            QueueRecord.service_id.isnot(None),
        )
        .group_by(QueueRecord.service_id, QueueRecord.service_name)
        .order_by(func.count(QueueRecord.id).desc())
        .limit(10)
        .all()
    )

    top_services = [
        {"service_id": r[0], "service_name": r[1] or "N/A", "count": r[2]}
        for r in top_services_rows
    ]

    return {
        "id": branch.id,
        "name": branch.name,
        "depart_name_mfc": branch.depart_name_mfc,
        "total_records": total_records,
        "num_employees": num_employees,
        "num_windows": num_windows,
        "avg_daily_visits": avg_daily_visits,
        "avg_wait_minutes": avg_wait_minutes,
        "avg_service_minutes": avg_service_minutes,
        "top_services": top_services,
    }
