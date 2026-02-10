"""SQLAlchemy ORM models for all database tables."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    depart_name_mfc: Mapped[str | None] = mapped_column(String, nullable=True)
    depart_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    employees: Mapped[list["Employee"]] = relationship(back_populates="branch")
    queue_records: Mapped[list["QueueRecord"]] = relationship(back_populates="branch")
    employee_roles: Mapped[list["EmployeeRole"]] = relationship(back_populates="branch")
    hourly_stats: Mapped[list["HourlyStat"]] = relationship(back_populates="branch")
    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="branch")
    branch_metadata: Mapped["BranchMetadata | None"] = relationship(back_populates="branch", uselist=False)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    fio: Mapped[str] = mapped_column(String, nullable=False)
    tab_num: Mapped[str | None] = mapped_column(String, nullable=True)
    branch_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("branches.id"), nullable=True
    )
    post: Mapped[str | None] = mapped_column(String, nullable=True)

    branch: Mapped["Branch | None"] = relationship(back_populates="employees")
    roles: Mapped[list["EmployeeRole"]] = relationship(back_populates="employee")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    name_short: Mapped[str | None] = mapped_column(String, nullable=True)
    normativ_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QueueRecord(Base):
    __tablename__ = "queue_records"
    __table_args__ = (
        Index("idx_queue_branch_date", "branch_id", "registered_at"),
        Index("idx_queue_result", "result_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("branches.id"), nullable=False
    )
    customer_number: Mapped[str | None] = mapped_column(String, nullable=True)
    employee_window: Mapped[str | None] = mapped_column(String, nullable=True)
    employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    called_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    wait_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_id: Mapped[int] = mapped_column(Integer, nullable=False)
    result_name: Mapped[str] = mapped_column(String, nullable=False)
    func_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    func_name: Mapped[str | None] = mapped_column(String, nullable=True)
    service_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("services.id"), nullable=True
    )
    service_name: Mapped[str | None] = mapped_column(String, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    service_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dossier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pre_registration: Mapped[bool] = mapped_column(Boolean, default=False)

    branch: Mapped["Branch"] = relationship(back_populates="queue_records")


class EmployeeRole(Base):
    __tablename__ = "employee_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=False
    )
    branch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("branches.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    role_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role_name: Mapped[str] = mapped_column(String, nullable=False)

    employee: Mapped["Employee"] = relationship(back_populates="roles")
    branch: Mapped["Branch"] = relationship(back_populates="employee_roles")


class HourlyStat(Base):
    __tablename__ = "hourly_stats"
    __table_args__ = (
        UniqueConstraint("branch_id", "date", "hour", name="uq_hourly_branch_date_hour"),
        Index("idx_hourly_branch_date", "branch_id", "date", "hour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("branches.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    total_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_wait_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_service_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_wait_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_service_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_windows_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    num_employees_active: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    branch: Mapped["Branch"] = relationship(back_populates="hourly_stats")


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint(
            "branch_id", "date", "hour", name="uq_forecast_branch_date_hour"
        ),
        Index("idx_forecast_branch_date", "branch_id", "date", "hour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("branches.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_visits: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_avg_wait: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_avg_service: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    branch: Mapped["Branch"] = relationship(back_populates="forecasts")


class BranchMetadata(Base):
    """Валидированные метаданные филиалов."""

    __tablename__ = "branch_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("branches.id"), nullable=False, unique=True
    )
    num_windows: Mapped[int] = mapped_column(Integer, nullable=False)
    num_windows_source: Mapped[str] = mapped_column(String, nullable=False)  # hourly_stats | queue_records | manual
    capacity_per_window: Mapped[int] = mapped_column(Integer, default=25)  # клиентов/окно/час
    max_capacity: Mapped[int] = mapped_column(Integer, nullable=False)  # num_windows * capacity_per_window

    validated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    confidence: Mapped[str] = mapped_column(String, nullable=False)  # high | medium | low
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    branch: Mapped["Branch"] = relationship(back_populates="branch_metadata")
