#!/usr/bin/env python3
"""CLI: generate forecasts for a given month (or arbitrary date range) and persist them to the DB.

Usage::

    # Monthly mode
    python scripts/generate_forecast.py \\
        --db-url sqlite:///./data/mfc.db \\
        --models-dir ./models \\
        --month 2026-03

    # Date range mode (30 days from a given date)
    python scripts/generate_forecast.py \\
        --db-url sqlite:///./data/mfc.db \\
        --models-dir ./models \\
        --from-date 2026-03-01 --days 30

    # Single branch
    python scripts/generate_forecast.py \\
        --db-url sqlite:///./data/mfc.db \\
        --models-dir ./models \\
        --month 2026-03 \\
        --branch-id 176
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
from multiprocessing import cpu_count
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the backend package is importable when running from the repo root.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ml.prediction import (
    generate_forecast,
    generate_forecast_range,
    load_models,
    save_forecast_to_db,
)

logger = logging.getLogger("generate_forecast")


def _generate_branch_forecast(
    bid: int, year: int, month: int, models_dir: str,
) -> tuple[int, list | None]:
    """Generate forecast for a single branch in a worker process."""
    from app.ml.prediction import generate_forecast, load_models

    models = load_models(models_dir)
    if bid not in models:
        return bid, None
    try:
        points = generate_forecast(bid, year, month, models)
        return bid, points
    except Exception:
        return bid, None


def _generate_branch_forecast_range(
    bid: int, start_date: date, end_date: date, models_dir: str,
) -> tuple[int, list | None]:
    """Generate forecast for a single branch over a date range in a worker process."""
    from app.ml.prediction import generate_forecast_range, load_models

    models = load_models(models_dir)
    if bid not in models:
        return bid, None
    try:
        points = generate_forecast_range(bid, start_date, end_date, models)
        return bid, points
    except Exception:
        return bid, None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate forecasts for MFC branches and save to DB.",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=os.environ.get("DATABASE_URL", "postgresql+psycopg2://mfc_user:mfc_pass@localhost:5432/mfc_db"),
        help="SQLAlchemy database URL",
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default="./models",
        help="Directory containing trained model files (default: ./models)",
    )

    # Mutually exclusive: --month OR --from-date/--days
    period_group = parser.add_mutually_exclusive_group(required=True)
    period_group.add_argument(
        "--month",
        type=str,
        default=None,
        help="Target month in YYYY-MM format (e.g. 2026-03).",
    )
    period_group.add_argument(
        "--from-date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format (default: today). Use with --days.",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to forecast from --from-date (default: 30).",
    )
    parser.add_argument(
        "--branch-id",
        type=int,
        default=None,
        help="Generate forecast for a single branch only.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel worker processes (default: all CPU cores).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser.parse_args()


def _parse_month(month_str: str) -> tuple[int, int]:
    """Parse ``"YYYY-MM"`` into ``(year, month)``."""
    parts = month_str.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid month format: {month_str!r} (expected YYYY-MM)")
    year = int(parts[0])
    month = int(parts[1])
    if month < 1 or month > 12:
        raise ValueError(f"Month out of range: {month}")
    return year, month


def _parse_date(date_str: str) -> date:
    """Parse ``"YYYY-MM-DD"`` into a :class:`date`."""
    try:
        return date.fromisoformat(date_str.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {date_str!r} (expected YYYY-MM-DD)") from exc


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Determine forecast mode: monthly or date-range
    use_range_mode = args.from_date is not None

    year: int | None = None
    month: int | None = None
    start_date: date | None = None
    end_date: date | None = None

    if use_range_mode:
        # Date-range mode
        try:
            start_date = _parse_date(args.from_date)
        except ValueError as exc:
            logger.error("Invalid --from-date value: %s", exc)
            sys.exit(1)

        if args.days < 1:
            logger.error("--days must be >= 1, got %d", args.days)
            sys.exit(1)

        end_date = start_date + timedelta(days=args.days - 1)

        logger.info("=== MFC Forecast Generation (date range) ===")
        logger.info("Date range   : %s .. %s (%d days)", start_date, end_date, args.days)
    else:
        # Monthly mode
        try:
            year, month = _parse_month(args.month)
        except ValueError as exc:
            logger.error("Invalid --month value: %s", exc)
            sys.exit(1)

        logger.info("=== MFC Forecast Generation ===")
        logger.info("Target month : %04d-%02d", year, month)

    logger.info("Models dir   : %s", args.models_dir)
    logger.info("Database     : %s", args.db_url)

    # Load models
    models = load_models(args.models_dir)
    if not models:
        logger.error("No models found in %s. Run train_model.py first.", args.models_dir)
        sys.exit(1)

    # Filter to single branch if requested
    branch_ids: list[int]
    if args.branch_id is not None:
        if args.branch_id not in models:
            logger.error(
                "No model for branch %d. Available: %s",
                args.branch_id,
                sorted(models.keys()),
            )
            sys.exit(1)
        branch_ids = [args.branch_id]
    else:
        branch_ids = sorted(models.keys())

    n_workers = args.workers or cpu_count() or 4
    logger.info("Generating forecasts for %d branch(es) using %d workers", len(branch_ids), n_workers)

    # Connect to DB (for saving results)
    connect_args = {}
    if "sqlite" in args.db_url:
        connect_args = {"check_same_thread": False}

    engine_kwargs = {"echo": False}
    if "sqlite" not in args.db_url:
        engine_kwargs["pool_size"] = 5
        engine_kwargs["pool_pre_ping"] = True

    engine = create_engine(args.db_url, connect_args=connect_args, **engine_kwargs)
    Session = sessionmaker(bind=engine)
    session = Session()

    total_points = 0
    t0 = time.time()

    # Generate forecasts in parallel, save sequentially (DB session)
    if n_workers > 1 and len(branch_ids) > 1:
        results: dict[int, list | None] = {}
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            if use_range_mode:
                futures = {
                    pool.submit(
                        _generate_branch_forecast_range, bid,
                        start_date, end_date, args.models_dir,
                    ): bid
                    for bid in branch_ids
                }
            else:
                futures = {
                    pool.submit(
                        _generate_branch_forecast, bid,
                        year, month, args.models_dir,
                    ): bid
                    for bid in branch_ids
                }
            for fut in as_completed(futures):
                bid = futures[fut]
                try:
                    _, points = fut.result()
                    results[bid] = points
                except Exception:
                    logger.exception("  Failed to generate forecast for branch %d", bid)
                    results[bid] = None

        # Save results sequentially
        for idx, bid in enumerate(branch_ids, 1):
            points = results.get(bid)
            if not points:
                logger.warning("[%d/%d] Branch %d: no forecast points", idx, len(branch_ids), bid)
                continue
            saved = save_forecast_to_db(session, bid, points)
            total_points += saved
            logger.info("[%d/%d] Branch %d: %d points saved", idx, len(branch_ids), bid, saved)
    else:
        for idx, bid in enumerate(branch_ids, 1):
            logger.info("[%d/%d] Branch %d", idx, len(branch_ids), bid)
            try:
                if use_range_mode:
                    points = generate_forecast_range(bid, start_date, end_date, models)
                else:
                    points = generate_forecast(bid, year, month, models)
            except Exception:
                logger.exception("  Failed to generate forecast for branch %d", bid)
                continue
            if not points:
                logger.warning("  No forecast points generated (empty period?)")
                continue
            saved = save_forecast_to_db(session, bid, points)
            total_points += saved
            logger.info("  %d points saved", saved)

    elapsed = time.time() - t0

    logger.info("=== Forecast Generation Complete ===")
    logger.info("Branches processed : %d", len(branch_ids))
    logger.info("Total points saved : %d", total_points)
    logger.info("Total time         : %.1fs", elapsed)

    session.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
