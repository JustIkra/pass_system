"""ETL service: CSV parsing and loading into the database.

Optimized for PostgreSQL with COPY protocol and multi-process parallel loading.
Uses ProcessPoolExecutor for CPU-bound CSV parsing (bypasses GIL) and
PostgreSQL COPY FROM for bulk inserts.
"""

from __future__ import annotations

import io
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from multiprocessing import cpu_count
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Branch,
    Employee,
    EmployeeRole,
    Forecast,
    HourlyStat,
    QueueRecord,
    Service,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _time_str_to_seconds(val: str | None) -> int | None:
    if not val or pd.isna(val) or str(val).strip() == "":
        return None
    val = str(val).strip()
    parts = val.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return h * 3600 + m * 60 + s
    except (ValueError, TypeError):
        return None


def _parse_datetime(date_str: str | None, time_str: str | None) -> datetime | None:
    if not date_str or pd.isna(date_str) or str(date_str).strip() == "":
        return None
    date_s = str(date_str).strip()
    try:
        dt = datetime.strptime(date_s, "%d.%m.%Y")
    except ValueError:
        return None
    if time_str and not pd.isna(time_str) and str(time_str).strip():
        time_s = str(time_str).strip()
        parts = time_s.split(":")
        if len(parts) == 3:
            try:
                dt = dt.replace(
                    hour=int(parts[0]), minute=int(parts[1]), second=int(parts[2])
                )
            except (ValueError, TypeError):
                pass
    return dt


def _safe_int(val: Any) -> int | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, str):
        val = val.strip()
        if val == "" or val.upper() == "NULL":
            return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_str(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if s == "" or s.upper() == "NULL":
        return None
    return s


def _find_files(data_dir: str, pattern: str) -> list[str]:
    base = Path(data_dir)
    files = sorted(base.rglob(pattern))
    return [str(f) for f in files]


def _escape_copy_val(v: Any) -> str:
    """Escape a value for PostgreSQL COPY TSV format."""
    if v is None:
        return "\\N"
    s = str(v)
    s = s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    return s


# ---------------------------------------------------------------------------
# PostgreSQL COPY-based bulk loader
# ---------------------------------------------------------------------------


def _copy_dataframe_to_table(
    df: pd.DataFrame,
    table_name: str,
    columns: list[str],
    db_url: str,
) -> int:
    """Load a DataFrame into PostgreSQL using COPY FROM (fastest method)."""
    if df.empty:
        return 0

    buf = io.StringIO()
    for _, row in df.iterrows():
        line = "\t".join(_escape_copy_val(row.get(c)) for c in columns)
        buf.write(line + "\n")

    buf.seek(0)
    cols_str = ", ".join(columns)
    copy_sql = f"COPY {table_name} ({cols_str}) FROM STDIN WITH (FORMAT text, NULL '\\N')"

    engine = create_engine(db_url, pool_size=1, max_overflow=0)
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.copy_expert(copy_sql, buf)
        raw_conn.commit()
        return len(df)
    finally:
        raw_conn.close()
        engine.dispose()


def _copy_tsv_buffer_to_table(
    tsv_buffer: str,
    row_count: int,
    table_name: str,
    columns: list[str],
    db_url: str,
) -> int:
    """Load a pre-built TSV buffer into PostgreSQL using COPY FROM.

    This variant accepts a raw TSV string (built in a worker process)
    so we avoid pickling DataFrames back to the main process.
    """
    if row_count == 0:
        return 0

    buf = io.StringIO(tsv_buffer)
    cols_str = ", ".join(columns)
    copy_sql = f"COPY {table_name} ({cols_str}) FROM STDIN WITH (FORMAT text, NULL '\\N')"

    engine = create_engine(db_url, pool_size=1, max_overflow=0)
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.copy_expert(copy_sql, buf)
        raw_conn.commit()
        return row_count
    finally:
        raw_conn.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Vectorized parsers (pandas-native, no iterrows for hot paths)
# ---------------------------------------------------------------------------


def _vectorized_parse_datetime(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    """Parse DD.MM.YYYY + HH:MM:SS columns into datetime, vectorized."""
    date_clean = date_series.fillna("").astype(str).str.strip()
    time_clean = time_series.fillna("00:00:00").astype(str).str.strip()
    time_clean = time_clean.replace("", "00:00:00")
    combined = date_clean + " " + time_clean
    result = pd.to_datetime(combined, format="%d.%m.%Y %H:%M:%S", errors="coerce")
    return result


def _vectorized_time_to_seconds(series: pd.Series) -> pd.Series:
    """Convert HH:MM:SS string series to seconds, vectorized."""
    clean = series.fillna("").astype(str).str.strip()
    parts = clean.str.split(":", expand=True)
    if parts.shape[1] < 3:
        return pd.Series([None] * len(series), dtype="Int64")
    h = pd.to_numeric(parts[0], errors="coerce")
    m = pd.to_numeric(parts[1], errors="coerce")
    s = pd.to_numeric(parts[2], errors="coerce")
    result = h * 3600 + m * 60 + s
    return result.astype("Int64")


# ---------------------------------------------------------------------------
# Queue record columns for COPY
# ---------------------------------------------------------------------------

QUEUE_COPY_COLUMNS = [
    "branch_id", "customer_number", "employee_window", "employee_id",
    "registered_at", "called_at", "wait_seconds", "result_id", "result_name",
    "func_id", "func_name", "service_id", "service_name",
    "ended_at", "service_seconds", "dossier_id", "pre_registration",
]

ROLES_COPY_COLUMNS = [
    "employee_id", "branch_id", "started_at", "ended_at", "role_id", "role_name",
]


# ---------------------------------------------------------------------------
# Worker functions for ProcessPoolExecutor
# ---------------------------------------------------------------------------


def _parse_queue_csv(fpath: str) -> dict[str, Any]:
    """Parse a single queue CSV file in a worker process (CPU-bound).

    Returns parsed TSV buffer + metadata. Does NOT touch the database.
    This runs in a child process via ProcessPoolExecutor to bypass the GIL.
    """
    fname = os.path.basename(fpath)
    t0 = datetime.now()

    try:
        df = pd.read_csv(
            fpath, sep=";", encoding="utf-8", dtype=str,
            low_memory=False, on_bad_lines="skip",
        )
    except Exception as exc:
        return {"file": fname, "tsv": "", "row_count": 0, "skipped": 0,
                "branch_names": {}, "error": str(exc)}

    df.columns = [c.strip() for c in df.columns]
    initial_len = len(df)

    # Vectorized transforms
    df["branch_id"] = pd.to_numeric(df.get("Branch_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df = df.dropna(subset=["branch_id"])

    df["registered_at"] = _vectorized_parse_datetime(
        df.get("Data_zapis", pd.Series(dtype=str)),
        df.get("Time_zapis", pd.Series(dtype=str)),
    )
    df = df.dropna(subset=["registered_at"])

    df["result_id"] = pd.to_numeric(df.get("Customer_result_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["result_name"] = df.get("Customer_result", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
    df = df.dropna(subset=["result_id"])
    df = df[df["result_name"] != ""]

    df["customer_number"] = df.get("Customer_number_Queue", pd.Series(dtype=str)).where(
        df.get("Customer_number_Queue", pd.Series(dtype=str)).notna()
    )
    df["employee_window"] = df.get("Employee_window", pd.Series(dtype=str)).where(
        df.get("Employee_window", pd.Series(dtype=str)).notna()
    )
    df["employee_id"] = pd.to_numeric(df.get("Employee_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")

    df["called_at"] = _vectorized_parse_datetime(
        df.get("Data_vizov", pd.Series(dtype=str)),
        df.get("Time_vizov", pd.Series(dtype=str)),
    )
    df["wait_seconds"] = _vectorized_time_to_seconds(df.get("Time_wait_vizov", pd.Series(dtype=str)))

    df["func_id"] = pd.to_numeric(df.get("Employee_func_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["func_name"] = df.get("Employee_func", pd.Series(dtype=str))

    df["service_id"] = pd.to_numeric(df.get("Provided_service_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["service_name"] = df.get("Provided_service", pd.Series(dtype=str))

    df["ended_at"] = _vectorized_parse_datetime(
        df.get("Data_end", pd.Series(dtype=str)),
        df.get("Time_end", pd.Series(dtype=str)),
    )
    df["service_seconds"] = _vectorized_time_to_seconds(df.get("Time_priem", pd.Series(dtype=str)))

    df["dossier_id"] = pd.to_numeric(df.get("ID_dossier", pd.Series(dtype=str)), errors="coerce").astype("Int64")

    pre_reg = df.get("Pre_registration", pd.Series(dtype=str)).fillna("0").astype(str).str.strip()
    df["pre_registration"] = (pre_reg == "1")

    # Collect branch names
    branch_names: dict[int, str] = {}
    if "Branch_name" in df.columns:
        bn = df[["branch_id", "Branch_name"]].dropna().drop_duplicates(subset=["branch_id"])
        for _, r in bn.iterrows():
            bname = _safe_str(r["Branch_name"])
            if bname:
                branch_names[int(r["branch_id"])] = bname

    # Build TSV buffer in-process (avoids pickling large DataFrame)
    out_df = df[QUEUE_COPY_COLUMNS].copy()
    row_count = len(out_df)

    tsv_lines: list[str] = []
    for _, row in out_df.iterrows():
        line = "\t".join(_escape_copy_val(row.get(c)) for c in QUEUE_COPY_COLUMNS)
        tsv_lines.append(line)
    tsv_buffer = "\n".join(tsv_lines) + "\n" if tsv_lines else ""

    skipped = initial_len - row_count
    elapsed = (datetime.now() - t0).total_seconds()

    return {
        "file": fname,
        "tsv": tsv_buffer,
        "row_count": row_count,
        "skipped": skipped,
        "branch_names": branch_names,
        "parse_seconds": round(elapsed, 1),
    }


def _parse_roles_csv(fpath: str) -> dict[str, Any]:
    """Parse a single roles CSV file in a worker process (CPU-bound).

    Returns parsed TSV buffer + metadata. Does NOT touch the database.
    """
    fname = os.path.basename(fpath)
    t0 = datetime.now()

    try:
        df = pd.read_csv(
            fpath, sep=";", encoding="utf-8", dtype=str,
            low_memory=False, on_bad_lines="skip",
        )
    except Exception as exc:
        return {"file": fname, "tsv": "", "row_count": 0, "error": str(exc)}

    df.columns = [c.strip() for c in df.columns]

    df["employee_id"] = pd.to_numeric(df.get("Employee_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["branch_id"] = pd.to_numeric(df.get("Branch_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df = df.dropna(subset=["employee_id", "branch_id"])

    df["started_at"] = _vectorized_parse_datetime(
        df.get("Date_begin", pd.Series(dtype=str)),
        df.get("Time_begin", pd.Series(dtype=str)),
    )
    df["ended_at"] = _vectorized_parse_datetime(
        df.get("Date_end", pd.Series(dtype=str)),
        df.get("Time_end", pd.Series(dtype=str)),
    )
    df = df.dropna(subset=["started_at", "ended_at"])

    df["role_id"] = pd.to_numeric(df.get("Role_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["role_name"] = df.get("Role_Name", pd.Series(dtype=str)).fillna("").str.strip()
    df = df.dropna(subset=["role_id"])
    df = df[df["role_name"] != ""]

    out_df = df[ROLES_COPY_COLUMNS].copy()
    row_count = len(out_df)

    tsv_lines: list[str] = []
    for _, row in out_df.iterrows():
        line = "\t".join(_escape_copy_val(row.get(c)) for c in ROLES_COPY_COLUMNS)
        tsv_lines.append(line)
    tsv_buffer = "\n".join(tsv_lines) + "\n" if tsv_lines else ""

    elapsed = (datetime.now() - t0).total_seconds()

    return {
        "file": fname,
        "tsv": tsv_buffer,
        "row_count": row_count,
        "parse_seconds": round(elapsed, 1),
    }


def _load_single_queue_file(fpath: str, db_url: str) -> dict[str, Any]:
    """Parse and load a single queue CSV file via COPY. Process-safe.

    Combined parse+load for backward compatibility with single-process mode.
    """
    fname = os.path.basename(fpath)
    logger.info("  [worker] Parsing %s", fname)
    t0 = datetime.now()

    try:
        df = pd.read_csv(
            fpath, sep=";", encoding="utf-8", dtype=str,
            low_memory=False, on_bad_lines="skip",
        )
    except Exception as exc:
        logger.error("  [worker] Failed to read %s: %s", fname, exc)
        return {"file": fname, "loaded": 0, "skipped": 0, "error": str(exc)}

    df.columns = [c.strip() for c in df.columns]
    initial_len = len(df)

    # Vectorized transforms
    df["branch_id"] = pd.to_numeric(df.get("Branch_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df = df.dropna(subset=["branch_id"])

    df["registered_at"] = _vectorized_parse_datetime(
        df.get("Data_zapis", pd.Series(dtype=str)),
        df.get("Time_zapis", pd.Series(dtype=str)),
    )
    df = df.dropna(subset=["registered_at"])

    df["result_id"] = pd.to_numeric(df.get("Customer_result_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["result_name"] = df.get("Customer_result", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
    df = df.dropna(subset=["result_id"])
    df = df[df["result_name"] != ""]

    df["customer_number"] = df.get("Customer_number_Queue", pd.Series(dtype=str)).where(
        df.get("Customer_number_Queue", pd.Series(dtype=str)).notna()
    )
    df["employee_window"] = df.get("Employee_window", pd.Series(dtype=str)).where(
        df.get("Employee_window", pd.Series(dtype=str)).notna()
    )
    df["employee_id"] = pd.to_numeric(df.get("Employee_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")

    df["called_at"] = _vectorized_parse_datetime(
        df.get("Data_vizov", pd.Series(dtype=str)),
        df.get("Time_vizov", pd.Series(dtype=str)),
    )
    df["wait_seconds"] = _vectorized_time_to_seconds(df.get("Time_wait_vizov", pd.Series(dtype=str)))

    df["func_id"] = pd.to_numeric(df.get("Employee_func_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["func_name"] = df.get("Employee_func", pd.Series(dtype=str))

    df["service_id"] = pd.to_numeric(df.get("Provided_service_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["service_name"] = df.get("Provided_service", pd.Series(dtype=str))

    df["ended_at"] = _vectorized_parse_datetime(
        df.get("Data_end", pd.Series(dtype=str)),
        df.get("Time_end", pd.Series(dtype=str)),
    )
    df["service_seconds"] = _vectorized_time_to_seconds(df.get("Time_priem", pd.Series(dtype=str)))

    df["dossier_id"] = pd.to_numeric(df.get("ID_dossier", pd.Series(dtype=str)), errors="coerce").astype("Int64")

    pre_reg = df.get("Pre_registration", pd.Series(dtype=str)).fillna("0").astype(str).str.strip()
    df["pre_registration"] = (pre_reg == "1")

    # Collect branch names
    branch_names: dict[int, str] = {}
    if "Branch_name" in df.columns:
        bn = df[["branch_id", "Branch_name"]].dropna().drop_duplicates(subset=["branch_id"])
        for _, r in bn.iterrows():
            bname = _safe_str(r["Branch_name"])
            if bname:
                branch_names[int(r["branch_id"])] = bname

    out_df = df[QUEUE_COPY_COLUMNS].copy()

    loaded = _copy_dataframe_to_table(out_df, "queue_records", QUEUE_COPY_COLUMNS, db_url)
    skipped = initial_len - loaded
    elapsed = (datetime.now() - t0).total_seconds()
    logger.info("  [worker] %s: loaded %d, skipped %d in %.1fs", fname, loaded, skipped, elapsed)

    return {"file": fname, "loaded": loaded, "skipped": skipped, "branch_names": branch_names}


def _load_single_roles_file(fpath: str, db_url: str) -> dict[str, Any]:
    """Parse and load a single roles CSV file via COPY. Process-safe."""
    fname = os.path.basename(fpath)
    logger.info("  [worker] Parsing roles %s", fname)
    t0 = datetime.now()

    try:
        df = pd.read_csv(
            fpath, sep=";", encoding="utf-8", dtype=str,
            low_memory=False, on_bad_lines="skip",
        )
    except Exception as exc:
        logger.error("  [worker] Failed to read %s: %s", fname, exc)
        return {"file": fname, "loaded": 0, "error": str(exc)}

    df.columns = [c.strip() for c in df.columns]

    df["employee_id"] = pd.to_numeric(df.get("Employee_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["branch_id"] = pd.to_numeric(df.get("Branch_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df = df.dropna(subset=["employee_id", "branch_id"])

    df["started_at"] = _vectorized_parse_datetime(
        df.get("Date_begin", pd.Series(dtype=str)),
        df.get("Time_begin", pd.Series(dtype=str)),
    )
    df["ended_at"] = _vectorized_parse_datetime(
        df.get("Date_end", pd.Series(dtype=str)),
        df.get("Time_end", pd.Series(dtype=str)),
    )
    df = df.dropna(subset=["started_at", "ended_at"])

    df["role_id"] = pd.to_numeric(df.get("Role_ID", pd.Series(dtype=str)), errors="coerce").astype("Int64")
    df["role_name"] = df.get("Role_Name", pd.Series(dtype=str)).fillna("").str.strip()
    df = df.dropna(subset=["role_id"])
    df = df[df["role_name"] != ""]

    out_df = df[ROLES_COPY_COLUMNS].copy()

    loaded = _copy_dataframe_to_table(out_df, "employee_roles", ROLES_COPY_COLUMNS, db_url)
    elapsed = (datetime.now() - t0).total_seconds()
    logger.info("  [worker] %s: loaded %d roles in %.1fs", fname, loaded, elapsed)

    return {"file": fname, "loaded": loaded}


# ---------------------------------------------------------------------------
# Reference data parsers (small datasets — keep simple)
# ---------------------------------------------------------------------------


def parse_branches_csv(data_dir: str, db: Session) -> int:
    files = _find_files(data_dir, "Справочник филиалов*.csv")
    if not files:
        logger.warning("No branch reference files found in %s", data_dir)
        return 0

    loaded = 0
    for fpath in files:
        logger.info("Parsing branches from %s", fpath)
        df = pd.read_csv(fpath, sep=";", encoding="utf-8", dtype=str, quotechar='"')
        df.columns = [c.strip().strip('"') for c in df.columns]

        for _, row in df.iterrows():
            branch_id = _safe_int(row.get("Branch"))
            if branch_id is None:
                continue
            depart_name = _safe_str(row.get("Depart_name_mfc"))
            depart_id = _safe_int(row.get("Depart_id"))

            existing = db.get(Branch, branch_id)
            if existing:
                existing.depart_name_mfc = depart_name
                existing.depart_id = depart_id
            else:
                db.add(Branch(id=branch_id, depart_name_mfc=depart_name, depart_id=depart_id))
            loaded += 1

    db.commit()
    logger.info("Branches loaded: %d", loaded)
    return loaded


def parse_services_csv(data_dir: str, db: Session) -> int:
    files = _find_files(data_dir, "Нормативы длительности услуг*только заполненные*.csv")
    if not files:
        files = _find_files(data_dir, "Нормативы длительности услуг*.csv")
    if not files:
        logger.warning("No service norms files found in %s", data_dir)
        return 0

    fpath = files[0]
    for f in files:
        if "только заполненные" in f:
            fpath = f
            break

    logger.info("Parsing services from %s", fpath)
    df = pd.read_csv(fpath, sep=";", encoding="utf-8", dtype=str, quotechar='"')
    df.columns = [c.strip().strip('"') for c in df.columns]

    loaded = 0
    for _, row in df.iterrows():
        sid = _safe_int(row.get("id"))
        if sid is None:
            continue
        name = _safe_str(row.get("provided_service_f")) or ""
        name_short = _safe_str(row.get("provided_service_s"))
        normativ = _safe_int(row.get("provided_service_normativ"))

        existing = db.get(Service, sid)
        if existing:
            existing.name = name
            existing.name_short = name_short
            existing.normativ_minutes = normativ
        else:
            db.add(Service(id=sid, name=name, name_short=name_short, normativ_minutes=normativ))
        loaded += 1

    db.commit()
    logger.info("Services loaded: %d", loaded)
    return loaded


def parse_employees_csv(data_dir: str, db: Session) -> int:
    files = sorted(_find_files(data_dir, "Справочник специалистов*.csv"))
    if not files:
        logger.warning("No employee files found")
        return 0

    loaded = 0
    duplicates = 0
    for fpath in files:
        logger.info("Parsing employees from %s", os.path.basename(fpath))
        df = pd.read_csv(fpath, sep=";", encoding="utf-8", dtype=str, quotechar='"')
        df.columns = [c.strip().strip('"') for c in df.columns]

        for _, row in df.iterrows():
            eid = _safe_int(row.get("Employee_ID"))
            if eid is None:
                continue
            fio = _safe_str(row.get("FIO")) or "N/A"
            tab_num = _safe_str(row.get("Tab_num"))
            branch_id = _safe_int(row.get("Branch"))
            post = _safe_str(row.get("Post"))

            if branch_id is not None and db.get(Branch, branch_id) is None:
                db.add(Branch(id=branch_id))
                db.flush()

            existing = db.get(Employee, eid)
            if existing:
                existing.fio = fio
                existing.tab_num = tab_num
                existing.branch_id = branch_id
                existing.post = post
                duplicates += 1
            else:
                db.add(Employee(id=eid, fio=fio, tab_num=tab_num, branch_id=branch_id, post=post))
            loaded += 1

    db.commit()
    logger.info("Employees loaded: %d records from %d files, %d duplicates", loaded, len(files), duplicates)
    return loaded


# ---------------------------------------------------------------------------
# Hourly stats aggregation
# ---------------------------------------------------------------------------


def aggregate_hourly_stats(db: Session) -> int:
    logger.info("Aggregating hourly_stats from queue_records...")

    db.execute(text("DELETE FROM hourly_stats"))
    db.commit()

    insert_sql = text("""
        INSERT INTO hourly_stats (
            branch_id, date, hour, total_visits, accepted_visits,
            avg_wait_seconds, avg_service_seconds,
            avg_wait_minutes, avg_service_minutes,
            num_windows_active, num_employees_active
        )
        SELECT
            branch_id,
            CAST(registered_at AS DATE) as date,
            CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER) as hour,
            COUNT(*) as total_visits,
            SUM(CASE WHEN result_id = 1 THEN 1 ELSE 0 END) as accepted_visits,
            AVG(CASE WHEN wait_seconds IS NOT NULL THEN wait_seconds END) as avg_wait_seconds,
            AVG(CASE WHEN service_seconds IS NOT NULL THEN service_seconds END) as avg_service_seconds,
            AVG(CASE WHEN wait_seconds IS NOT NULL THEN wait_seconds / 60.0 END) as avg_wait_minutes,
            AVG(CASE WHEN service_seconds IS NOT NULL THEN service_seconds / 60.0 END) as avg_service_minutes,
            COUNT(DISTINCT CASE WHEN employee_window IS NOT NULL THEN employee_window END) as num_windows_active,
            COUNT(DISTINCT CASE WHEN employee_id IS NOT NULL THEN employee_id END) as num_employees_active
        FROM queue_records
        GROUP BY branch_id, CAST(registered_at AS DATE), CAST(EXTRACT(HOUR FROM registered_at) AS INTEGER)
    """)

    db.execute(insert_sql)
    db.commit()

    count = db.execute(text("SELECT COUNT(*) FROM hourly_stats")).scalar()
    logger.info("Hourly stats aggregated: %d records", count)
    return count or 0


# ---------------------------------------------------------------------------
# Main ETL entry point — multi-process parallel
# ---------------------------------------------------------------------------


def load_all_parallel(
    data_dir: str,
    db: Session,
    db_url: str,
    max_workers: int = 120,
) -> dict[str, Any]:
    """
    Run the full ETL pipeline with multi-process parallel file loading.

    Architecture (2-phase pipeline):
      Phase 1 — CPU-bound CSV parsing in ProcessPoolExecutor (bypasses GIL)
      Phase 2 — I/O-bound COPY to PostgreSQL (sequential, fast)

    Reference data (branches, services, employees) loaded sequentially (small).
    Queue records and roles parsed in parallel, then COPY'd to DB.
    """
    summary: dict[str, Any] = {}
    n_cpu = cpu_count() or 4

    # For parsing, use CPU core count (ProcessPoolExecutor).
    # For DB writes, the existing COPY approach is already fast.
    n_parse_workers = min(max_workers, n_cpu, 16)  # cap at 16 to avoid memory pressure

    logger.info("=" * 60)
    logger.info("Starting MULTI-PROCESS ETL pipeline")
    logger.info("  Parse workers (processes): %d", n_parse_workers)
    logger.info("  DB COPY workers (threads): sequential (COPY is already fast)")
    logger.info("  Data dir: %s", data_dir)
    logger.info("=" * 60)

    start = datetime.now()

    # 1. Reference data — small, sequential, needs upsert
    summary["branches"] = parse_branches_csv(data_dir, db)
    summary["services"] = parse_services_csv(data_dir, db)
    summary["employees"] = parse_employees_csv(data_dir, db)

    # 2. Disable indexes and constraints for bulk loading
    logger.info("Disabling indexes for bulk load...")
    db.execute(text("SET session_replication_role = 'replica'"))
    db.commit()

    # 3. Discover files
    queue_files = sorted(_find_files(data_dir, "Статистика ЭО для WMF*.csv"))
    roles_files = sorted(_find_files(data_dir, "Журнал ролей специалистов*.csv"))

    logger.info(
        "Found %d queue files + %d roles files. Parsing with %d processes...",
        len(queue_files), len(roles_files), n_parse_workers,
    )

    total_queue_loaded = 0
    total_queue_skipped = 0
    total_roles_loaded = 0
    branch_names: dict[int, str] = {}

    # 4. Phase 1: Parse all CSV files in parallel processes
    #    Phase 2: COPY parsed TSV buffers to DB sequentially
    all_parse_tasks: list[tuple[str, str]] = (
        [(f, "queue") for f in queue_files] + [(f, "roles") for f in roles_files]
    )

    if not all_parse_tasks:
        logger.warning("No CSV files found to process")
    elif n_parse_workers <= 1 or len(all_parse_tasks) <= 1:
        # Sequential fallback
        for fpath, ftype in all_parse_tasks:
            if ftype == "queue":
                result = _load_single_queue_file(fpath, db_url)
                total_queue_loaded += result.get("loaded", 0)
                total_queue_skipped += result.get("skipped", 0)
                for bid, bname in result.get("branch_names", {}).items():
                    branch_names[bid] = bname
            else:
                result = _load_single_roles_file(fpath, db_url)
                total_roles_loaded += result.get("loaded", 0)
    else:
        # Multi-process: parse in parallel, then COPY sequentially
        parse_results: list[tuple[str, dict[str, Any]]] = []

        with ProcessPoolExecutor(max_workers=n_parse_workers) as pool:
            futures = {}
            for fpath, ftype in all_parse_tasks:
                if ftype == "queue":
                    fut = pool.submit(_parse_queue_csv, fpath)
                else:
                    fut = pool.submit(_parse_roles_csv, fpath)
                futures[fut] = ftype

            for future in as_completed(futures):
                ftype = futures[future]
                try:
                    result = future.result()
                    parse_results.append((ftype, result))
                    logger.info(
                        "  [parsed] %s: %d rows in %.1fs",
                        result.get("file", "?"),
                        result.get("row_count", 0),
                        result.get("parse_seconds", 0),
                    )
                except Exception as exc:
                    logger.error("Parse worker failed: %s", exc)

        # Phase 2: COPY all parsed buffers to DB (sequential — fast I/O)
        logger.info("Loading %d parsed files to database via COPY...", len(parse_results))

        for ftype, result in parse_results:
            if result.get("error"):
                logger.error("  Skipping %s: %s", result.get("file"), result.get("error"))
                continue

            tsv_buffer = result.get("tsv", "")
            row_count = result.get("row_count", 0)

            if row_count == 0:
                continue

            if ftype == "queue":
                loaded = _copy_tsv_buffer_to_table(
                    tsv_buffer, row_count, "queue_records", QUEUE_COPY_COLUMNS, db_url,
                )
                total_queue_loaded += loaded
                total_queue_skipped += result.get("skipped", 0)
                for bid, bname in result.get("branch_names", {}).items():
                    branch_names[bid] = bname
            else:
                loaded = _copy_tsv_buffer_to_table(
                    tsv_buffer, row_count, "employee_roles", ROLES_COPY_COLUMNS, db_url,
                )
                total_roles_loaded += loaded

            logger.info(
                "  [COPY] %s: %d rows loaded", result.get("file", "?"), loaded,
            )

    summary["queue_records_loaded"] = total_queue_loaded
    summary["queue_records_skipped"] = total_queue_skipped
    summary["employee_roles"] = total_roles_loaded

    # 5. Update branch names from queue data
    for bid, bname in branch_names.items():
        branch = db.get(Branch, bid)
        if branch:
            if not branch.name:
                branch.name = bname
        else:
            db.add(Branch(id=bid, name=bname))
    db.commit()

    # 6. Re-enable constraints
    logger.info("Re-enabling constraints...")
    db.execute(text("SET session_replication_role = 'origin'"))
    db.commit()

    # 7. Aggregate hourly stats
    summary["hourly_stats"] = aggregate_hourly_stats(db)

    elapsed = (datetime.now() - start).total_seconds()
    summary["duration_seconds"] = round(elapsed, 1)
    summary["parse_workers"] = n_parse_workers

    logger.info("=" * 60)
    logger.info("ETL Summary (multi-process):")
    for k, v in summary.items():
        logger.info("  %-25s %s", k, f"{v:,}" if isinstance(v, int) else v)
    logger.info("Total time: %.1fs", elapsed)
    logger.info("=" * 60)

    return summary


# Keep old sequential interface for backwards compatibility
def load_all(data_dir: str, db: Session) -> dict[str, Any]:
    """Sequential fallback — use load_all_parallel for PostgreSQL."""
    from app.config import settings
    return load_all_parallel(data_dir, db, settings.DATABASE_URL, max_workers=1)
