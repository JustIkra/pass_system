"""Pydantic response schemas for all API endpoints."""

from datetime import date, datetime
from pydantic import BaseModel


# ---- Branch schemas ----


class DateRange(BaseModel):
    from_date: str | None = None
    to_date: str | None = None

    class Config:
        populate_by_name = True


class BranchListItem(BaseModel):
    id: int
    name: str | None
    depart_name_mfc: str | None
    total_records: int
    date_range: DateRange

    class Config:
        from_attributes = True


class ServiceStat(BaseModel):
    service_id: int
    service_name: str
    count: int


class BranchDetail(BaseModel):
    id: int
    name: str | None
    depart_name_mfc: str | None
    total_records: int
    num_employees: int
    num_windows: int
    avg_daily_visits: float
    avg_wait_minutes: float
    avg_service_minutes: float
    top_services: list[ServiceStat]

    class Config:
        from_attributes = True


# ---- Forecast schemas ----


class ForecastPoint(BaseModel):
    date: str
    hour: int
    predicted_visits: float
    predicted_avg_wait: float | None
    confidence_lower: float | None
    confidence_upper: float | None


class ForecastSummary(BaseModel):
    total_predicted_visits: float
    peak_day: str | None
    peak_hour: int | None
    avg_daily_visits: float


class ForecastResponse(BaseModel):
    branch_id: int
    branch_name: str | None
    month: str
    data: list[ForecastPoint]
    summary: ForecastSummary


# ---- Windows schemas ----


class WindowHourLoad(BaseModel):
    hour: int
    load_percent: float
    avg_visits: float


class WindowLoad(BaseModel):
    window_number: str
    avg_daily_load_percent: float
    load_by_hour: list[WindowHourLoad]
    status: str  # overloaded / normal / underloaded / idle


class WindowsResponse(BaseModel):
    branch_id: int
    month: str
    windows: list[WindowLoad]


# ---- Staffing schemas ----


class StaffingRecommendation(BaseModel):
    date: str
    hour: int
    predicted_visits: float
    avg_service_minutes: float
    required_windows: int
    current_windows_avg: int
    delta: int
    status: str  # understaffed / optimal / overstaffed


class StaffingResponse(BaseModel):
    branch_id: int
    month: str
    recommendations: list[StaffingRecommendation]


# ---- History schemas ----


class DailyHistory(BaseModel):
    date: str
    total_visits: int
    avg_wait_minutes: float | None
    avg_service_minutes: float | None
    peak_hour: int | None


class HourlyHistory(BaseModel):
    date: str
    hour: int
    total_visits: int
    avg_wait_minutes: float | None
    avg_service_minutes: float | None
    num_windows_active: int


class HistoryResponse(BaseModel):
    branch_id: int
    period: DateRange
    daily: list[DailyHistory]
    hourly: list[HourlyHistory]


# ---- Compare schemas ----


class ComparisonRow(BaseModel):
    id: int
    name: str | None
    predicted_total_visits: float
    predicted_avg_wait: float | None
    predicted_avg_service: float | None
    predicted_peak_hour: int | None
    required_avg_windows: float
    overloaded_hours_count: int


class ComparisonResponse(BaseModel):
    month: str
    branches: list[ComparisonRow]


# ---- Analytics Overview schemas ----


class OverloadedBranch(BaseModel):
    branch_id: int
    branch_name: str | None
    predicted_avg_wait: float
    overloaded_hours: int


class UnderloadedBranch(BaseModel):
    branch_id: int
    branch_name: str | None
    predicted_avg_wait: float
    avg_load_percent: float


class OverviewResponse(BaseModel):
    month: str
    total_branches: int
    total_predicted_visits: float
    avg_predicted_wait: float
    top_overloaded: list[OverloadedBranch]
    top_underloaded: list[UnderloadedBranch]


# ---- Upload / Model schemas ----


class UploadResponse(BaseModel):
    status: str
    records_loaded: int
    records_skipped: int
    duration_seconds: float


class ModelRetrainResponse(BaseModel):
    status: str
    message: str


class ModelStatusResponse(BaseModel):
    status: str
    progress: int
    total_branches: int
    current_branch: str | None
    started_at: str | None
