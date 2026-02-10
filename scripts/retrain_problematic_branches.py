#!/usr/bin/env python3
"""Retrain models for branches with high forecast errors.

This script identifies branches with poor forecast accuracy (wMAPE > 50%)
and retrains their models with outlier cleaning enabled. This helps fix
models that were initially trained on data with extreme outliers.

Usage::

    # Retrain all problematic branches (wMAPE > 50%)
    python scripts/retrain_problematic_branches.py

    # Retrain specific branches
    python scripts/retrain_problematic_branches.py --branch-ids 12,166

    # Custom threshold
    python scripts/retrain_problematic_branches.py --mape-threshold 40
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
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

from app.ml.training import train_all_models

logger = logging.getLogger("retrain_problematic")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retrain models for branches with high forecast errors.",
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
    parser.add_argument(
        "--validation-report",
        type=str,
        default=None,
        help="Path to validation_report.json (default: models_dir/validation_report.json)",
    )
    parser.add_argument(
        "--mape-threshold",
        type=float,
        default=50.0,
        help="wMAPE threshold for identifying problematic branches (default: 50%%)",
    )
    parser.add_argument(
        "--branch-ids",
        type=str,
        default=None,
        help="Comma-separated branch IDs to retrain (overrides threshold-based selection)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel worker processes (default: 4)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    return parser.parse_args()


def identify_problematic_branches(
    validation_report_path: Path, threshold: float
) -> list[int]:
    """Read validation report and return branch IDs with wMAPE > threshold."""
    if not validation_report_path.exists():
        logger.error("Validation report not found: %s", validation_report_path)
        logger.info("Run: python scripts/train_model.py --validate")
        return []

    with open(validation_report_path, encoding="utf-8") as f:
        report = json.load(f)

    branches = report.get("branches", [])
    problematic = [
        b["branch_id"] for b in branches
        if b.get("mape_daily", 0) > threshold
    ]

    if problematic:
        logger.info(
            "Found %d branches with wMAPE > %.0f%%: %s",
            len(problematic), threshold, sorted(problematic),
        )
    else:
        logger.info("No branches found with wMAPE > %.0f%%", threshold)

    return problematic


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=== Retrain Problematic Branches ===")

    # Determine which branches to retrain
    branch_ids: list[int]
    if args.branch_ids:
        # Explicit list
        branch_ids = [int(x.strip()) for x in args.branch_ids.split(",")]
        logger.info("Retraining explicitly specified branches: %s", branch_ids)
    else:
        # Use validation report
        val_report_path = (
            Path(args.validation_report)
            if args.validation_report
            else Path(args.models_dir) / "validation_report.json"
        )
        branch_ids = identify_problematic_branches(val_report_path, args.mape_threshold)

        if not branch_ids:
            logger.info("Nothing to retrain. Exiting.")
            sys.exit(0)

    logger.info("Database    : %s", args.db_url)
    logger.info("Models dir  : %s", args.models_dir)
    logger.info("Workers     : %d", args.workers)
    logger.info("Branches    : %d", len(branch_ids))

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

    # Retrain with outlier cleaning enabled
    logger.info("Starting retraining with outlier cleaning...")
    report = train_all_models(
        db_session=session,
        models_dir=args.models_dir,
        branch_ids=branch_ids,
        validate=True,  # Run validation to compare before/after
        test_split_date="2023-10-01",
        n_workers=args.workers,
        use_gpu=False,
        clean_outliers=True,
    )

    session.close()

    # Summary
    logger.info("=== Retraining Complete ===")
    logger.info("Branches retrained : %d", report["num_branches_trained"])
    logger.info("Branches skipped   : %d", len(report["branches_skipped"]))

    if report["branches_skipped"]:
        logger.info("Skipped branches:")
        for s in report["branches_skipped"]:
            logger.info("  branch_id=%s: %s", s["branch_id"], s["reason"])

    # Print validation results
    validated = [b for b in report["branches"] if "validation" in b]
    if validated:
        logger.info("=== Validation Results ===")
        for b in validated:
            v = b["validation"]
            logger.info(
                "  Branch %d: wMAPE=%.1f%%, MAE=%.2f, Peak=%.1f%%",
                b["branch_id"],
                v.get("mape", 0),
                v.get("mae", 0),
                v.get("peak_accuracy", 0) * 100,
            )

        mapes = [b["validation"]["mape"] for b in validated]
        avg_mape = sum(mapes) / len(mapes)
        under_25 = sum(1 for m in mapes if m < 25)

        logger.info("Average wMAPE : %.1f%%", avg_mape)
        logger.info(
            "wMAPE < 25%%   : %d / %d (%.0f%%)",
            under_25, len(mapes), under_25 / len(mapes) * 100,
        )

    logger.info("Done. Models saved to %s", args.models_dir)


if __name__ == "__main__":
    main()
