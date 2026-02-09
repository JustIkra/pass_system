#!/usr/bin/env python3
"""CLI: train Prophet models for all (or one) MFC branches.

Usage examples::

    # Train on all data, no validation
    python scripts/train_model.py --db-url sqlite:///./data/mfc.db --models-dir ./models

    # Train with backtesting (split at 2023-10-01)
    python scripts/train_model.py --db-url sqlite:///./data/mfc.db --models-dir ./models --validate

    # Train a single branch for debugging
    python scripts/train_model.py --db-url sqlite:///./data/mfc.db --models-dir ./models \\
        --branch-id 176 --validate
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from multiprocessing import cpu_count
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the backend package is importable when running from the repo root.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.ml.training import train_all_models

logger = logging.getLogger("train_model")

DEFAULT_TEST_SPLIT = "2023-10-01"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train Prophet forecasting models for MFC branches.",
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
        help="Directory to store trained model files (default: ./models)",
    )
    parser.add_argument(
        "--branch-id",
        type=int,
        default=None,
        help="Train only this branch (for debugging).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        default=False,
        help="Run backtesting (train 2023-01..2023-09, test 2023-10..2024-02).",
    )
    parser.add_argument(
        "--test-split",
        type=str,
        default=DEFAULT_TEST_SPLIT,
        help=f"Date for backtesting split (default: {DEFAULT_TEST_SPLIT}).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel worker processes for training (default: all CPU cores).",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        default=False,
        help="Enable GPU-accelerated training via CmdStanPy OpenCL backend.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    n_workers = args.workers or cpu_count() or 4

    logger.info("=== MFC Prophet Model Training ===")
    logger.info("Database : %s", args.db_url)
    logger.info("Models   : %s", args.models_dir)
    logger.info("Workers  : %d", n_workers)
    logger.info("GPU      : %s", args.gpu)
    logger.info("Validate : %s", args.validate)

    # Connect to DB
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

    # Verify data exists
    try:
        count_row = session.execute(text("SELECT COUNT(*) FROM hourly_stats")).fetchone()
        total_rows = count_row[0] if count_row else 0
        logger.info("hourly_stats contains %d rows", total_rows)
        if total_rows == 0:
            logger.error(
                "No data in hourly_stats. Run init_db.py first to load CSV data "
                "and aggregate hourly statistics."
            )
            sys.exit(1)
    except Exception as exc:
        logger.error("Cannot query hourly_stats: %s", exc)
        sys.exit(1)

    branch_ids: list[int] | None = None
    if args.branch_id is not None:
        branch_ids = [args.branch_id]
        logger.info("Training single branch: %d", args.branch_id)

    t0 = time.time()

    report = train_all_models(
        db_session=session,
        models_dir=args.models_dir,
        branch_ids=branch_ids,
        validate=args.validate,
        test_split_date=args.test_split if args.validate else None,
        n_workers=n_workers,
        use_gpu=args.gpu,
    )

    elapsed = time.time() - t0

    # ---- Print summary ----
    logger.info("=== Training Complete ===")
    logger.info("Branches trained : %d", report["num_branches_trained"])
    logger.info("Branches skipped : %d", len(report["branches_skipped"]))
    logger.info("Total time       : %.1fs", elapsed)
    logger.info(
        "Avg per branch   : %.1fs", report.get("avg_training_time_seconds", 0)
    )

    if report["branches_skipped"]:
        logger.info("Skipped branches:")
        for s in report["branches_skipped"]:
            logger.info("  branch_id=%s: %s", s["branch_id"], s["reason"])

    # Print validation summary if applicable
    if args.validate:
        validated = [
            b for b in report["branches"] if "validation" in b
        ]
        if validated:
            mapes = [b["validation"]["mape"] for b in validated]
            maes = [b["validation"]["mae"] for b in validated]
            peaks = [b["validation"]["peak_accuracy"] for b in validated]
            cis = [b["validation"]["ci_coverage"] for b in validated]

            logger.info("=== Validation Summary ===")
            logger.info("Branches validated  : %d", len(validated))
            logger.info(
                "wMAPE (mean/median) : %.1f%% / %.1f%%",
                sum(mapes) / len(mapes),
                sorted(mapes)[len(mapes) // 2],
            )
            logger.info(
                "MAE   (mean)        : %.2f",
                sum(maes) / len(maes),
            )
            logger.info(
                "Peak accuracy (mean): %.1f%%",
                sum(peaks) / len(peaks) * 100,
            )
            logger.info(
                "CI coverage   (mean): %.1f%%",
                sum(cis) / len(cis) * 100,
            )

            under_25 = sum(1 for m in mapes if m < 25)
            logger.info(
                "wMAPE < 25%% : %d / %d (%.0f%%)",
                under_25,
                len(mapes),
                under_25 / len(mapes) * 100,
            )

            # Save validation report
            val_report = {
                "branches": [
                    {
                        "branch_id": b["branch_id"],
                        "mape_daily": b["validation"]["mape"],
                        "mae_visits": b["validation"]["mae"],
                        "rmse": b["validation"]["rmse"],
                        "peak_accuracy": b["validation"]["peak_accuracy"],
                        "ci_coverage": b["validation"]["ci_coverage"],
                        "passed": b["validation"]["mape"] < 25,
                    }
                    for b in validated
                ],
                "summary": {
                    "branches_passed": under_25,
                    "branches_total": len(validated),
                    "avg_mape": round(sum(mapes) / len(mapes), 2),
                    "avg_mae": round(sum(maes) / len(maes), 4),
                    "avg_peak_accuracy": round(sum(peaks) / len(peaks), 4),
                    "avg_ci_coverage": round(sum(cis) / len(cis), 4),
                },
            }
            val_path = Path(args.models_dir) / "validation_report.json"
            with open(val_path, "w", encoding="utf-8") as f:
                json.dump(val_report, f, ensure_ascii=False, indent=2)
            logger.info("Validation report saved to %s", val_path)

    session.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
