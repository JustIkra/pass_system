#!/usr/bin/env python3
"""
Initialize the database: create tables, load all CSV data, aggregate hourly stats.

Supports massively parallel loading with PostgreSQL COPY protocol.

Usage:
    python scripts/init_db.py --data-dir "./Исходные данные АИС"
    python scripts/init_db.py --data-dir "./Исходные данные АИС" --drop-existing
    python scripts/init_db.py --data-dir "./Исходные данные АИС" --drop-existing --workers 120
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Branch,
    Employee,
    EmployeeRole,
    Forecast,
    HourlyStat,
    QueueRecord,
    Service,
)
from app.services.etl import load_all_parallel

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("init_db")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create database tables and load CSV data (parallel)."
    )
    parser.add_argument(
        "--data-dir",
        default=os.path.join(
            os.path.dirname(__file__), "..", "Исходные данные АИС"
        ),
        help="Path to CSV data directory",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", "postgresql+psycopg2://mfc_user:mfc_pass@localhost:5432/mfc_db"),
        help="Database connection URL",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop and recreate all tables",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=120,
        help="Number of parallel threads for bulk loading (default: 120)",
    )
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    db_url = args.db_url

    logger.info("Database URL: %s", db_url)
    logger.info("Data directory: %s", data_dir)
    logger.info("Workers: %d", args.workers)

    if not os.path.isdir(data_dir):
        logger.error("Data directory does not exist: %s", data_dir)
        sys.exit(1)

    # Ensure data/ directory exists for SQLite
    if "sqlite" in db_url:
        db_path = db_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(db_dir, exist_ok=True)

    # Create engine
    connect_args = {}
    if "sqlite" in db_url:
        connect_args["check_same_thread"] = False

    engine_kwargs: dict = {"echo": False}
    if "sqlite" not in db_url:
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20
        engine_kwargs["pool_pre_ping"] = True

    engine = create_engine(db_url, connect_args=connect_args, **engine_kwargs)

    if "sqlite" in db_url:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.close()

    Session = sessionmaker(bind=engine)

    # Create or recreate tables
    if args.drop_existing:
        logger.info("Dropping all tables...")
        Base.metadata.drop_all(bind=engine)

    logger.info("Creating tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Tables created.")

    # Tune PostgreSQL for bulk loading
    if "sqlite" not in db_url:
        logger.info("Tuning PostgreSQL for bulk import...")
        raw_conn = engine.raw_connection()
        try:
            raw_conn.set_isolation_level(0)  # AUTOCOMMIT
            cur = raw_conn.cursor()
            cur.execute("ALTER SYSTEM SET max_wal_size = '4GB'")
            cur.execute("ALTER SYSTEM SET checkpoint_completion_target = '0.9'")
            cur.execute("SELECT pg_reload_conf()")
            cur.close()
        except Exception as exc:
            logger.warning("Could not tune PostgreSQL: %s", exc)
        finally:
            raw_conn.close()

    # Load data
    start = time.time()
    db = Session()

    try:
        summary = load_all_parallel(data_dir, db, db_url, max_workers=args.workers)
    except Exception:
        db.rollback()
        logger.exception("ETL pipeline failed")
        sys.exit(1)
    finally:
        db.close()

    elapsed = time.time() - start

    # Print final summary
    logger.info("=" * 60)
    logger.info("=== Final Summary ===")

    db = Session()
    try:
        tables = {
            "branches": db.execute(text("SELECT COUNT(*) FROM branches")).scalar(),
            "employees": db.execute(text("SELECT COUNT(*) FROM employees")).scalar(),
            "services": db.execute(text("SELECT COUNT(*) FROM services")).scalar(),
            "queue_records": db.execute(text("SELECT COUNT(*) FROM queue_records")).scalar(),
            "employee_roles": db.execute(text("SELECT COUNT(*) FROM employee_roles")).scalar(),
            "hourly_stats": db.execute(text("SELECT COUNT(*) FROM hourly_stats")).scalar(),
        }
        for table, count in tables.items():
            logger.info("  %-20s %s", table + ":", f"{count:,}")
    finally:
        db.close()

    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    logger.info("  Total time: %dm %02ds", minutes, seconds)
    logger.info("=" * 60)
    logger.info("Done.")


if __name__ == "__main__":
    main()
