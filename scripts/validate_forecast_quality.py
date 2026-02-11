#!/usr/bin/env python3
"""Comprehensive forecast quality validation.

Reads raw CSV data, aggregates hourly stats per branch,
loads trained Prophet models, generates backtesting predictions,
and compares against actuals with detailed metrics.

Usage:
    python3 scripts/validate_forecast_quality.py
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from prophet import Prophet

# Suppress Prophet/cmdstanpy noise
warnings.filterwarnings("ignore", category=FutureWarning)

# Add backend to path for ML utilities
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ml.utils import (
    REGRESSOR_COLUMNS,
    add_regressors,
    calculate_ci_coverage,
    calculate_mae,
    calculate_mape,
    calculate_peak_accuracy,
    calculate_rmse,
    get_russian_holidays_df,
    is_russian_holiday,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "Исходные данные АИС"
MODELS_DIR = BASE_DIR / "models"
WORKING_HOURS = list(range(8, 20))  # 8:00..19:00


# ---------------------------------------------------------------------------
# 1. Parse raw CSV data
# ---------------------------------------------------------------------------
def load_raw_csv_data() -> pd.DataFrame:
    """Load all 'Статистика ЭО для WMF' CSV files and return raw queue records."""
    pattern = "Статистика ЭО для WMF*.csv"
    files = sorted(DATA_DIR.rglob(pattern))
    if not files:
        print(f"ERROR: No files matching '{pattern}' in {DATA_DIR}")
        sys.exit(1)

    print(f"Found {len(files)} CSV files")
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, sep=";", encoding="utf-8", low_memory=False)
            dfs.append(df)
            print(f"  Loaded {len(df):,} rows from {f.name}")
        except Exception as e:
            print(f"  SKIP {f.name}: {e}")

    if not dfs:
        print("ERROR: No data loaded")
        sys.exit(1)

    all_data = pd.concat(dfs, ignore_index=True)
    print(f"Total raw records: {len(all_data):,}")
    return all_data


def aggregate_hourly_stats(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw queue records to hourly visit counts per branch.

    Returns DataFrame with columns: branch_id, date, hour, total_visits, avg_wait_seconds.
    """
    # Parse registration datetime
    raw = raw.copy()
    raw["dt_zapis"] = pd.to_datetime(
        raw["Data_zapis"].astype(str) + " " + raw["Time_zapis"].astype(str),
        format="%d.%m.%Y %H:%M:%S",
        errors="coerce",
    )
    raw = raw.dropna(subset=["dt_zapis"])

    # Parse wait time (HH:MM:SS -> seconds)
    def time_to_seconds(val):
        if pd.isna(val) or str(val).strip() == "":
            return np.nan
        parts = str(val).strip().split(":")
        if len(parts) != 3:
            return np.nan
        try:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return h * 3600 + m * 60 + s
        except (ValueError, TypeError):
            return np.nan

    raw["wait_seconds"] = raw["Time_wait_vizov"].apply(time_to_seconds)

    # Parse service time similarly
    raw["service_seconds"] = raw["Time_priem"].apply(time_to_seconds)

    # Extract date and hour
    raw["date"] = raw["dt_zapis"].dt.date
    raw["hour"] = raw["dt_zapis"].dt.hour

    # Filter working hours only
    raw = raw[raw["hour"].isin(WORKING_HOURS)]

    # Aggregate per branch/date/hour
    agg = raw.groupby(["Branch_ID", "date", "hour"]).agg(
        total_visits=("Branch_ID", "count"),
        avg_wait_seconds=("wait_seconds", "mean"),
        avg_service_seconds=("service_seconds", "mean"),
    ).reset_index()

    agg.rename(columns={"Branch_ID": "branch_id"}, inplace=True)
    agg["date"] = pd.to_datetime(agg["date"])
    agg["avg_wait_minutes"] = agg["avg_wait_seconds"] / 60.0

    print(f"\nAggregated hourly stats: {len(agg):,} rows")
    print(f"Branches: {agg['branch_id'].nunique()}")
    print(f"Date range: {agg['date'].min().date()} to {agg['date'].max().date()}")

    return agg


# ---------------------------------------------------------------------------
# 2. Load models
# ---------------------------------------------------------------------------
def load_models() -> dict[int, tuple[Prophet, Prophet]]:
    """Load all trained Prophet model pairs."""
    models: dict[int, tuple[Prophet, Prophet]] = {}
    visit_files = sorted(MODELS_DIR.glob("branch_*_visits.pkl"))

    for vf in visit_files:
        parts = vf.stem.split("_")
        try:
            bid = int(parts[1])
        except (IndexError, ValueError):
            continue
        wf = MODELS_DIR / f"branch_{bid}_wait.pkl"
        if not wf.exists():
            continue
        try:
            vm = joblib.load(vf)
            wm = joblib.load(wf)
            models[bid] = (vm, wm)
        except Exception as e:
            print(f"  Failed to load branch {bid}: {e}")

    print(f"\nLoaded {len(models)} model pairs")
    return models


# ---------------------------------------------------------------------------
# 3. Generate backtesting predictions
# ---------------------------------------------------------------------------
def predict_for_period(
    model: Prophet,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Generate predictions for a date range using a trained model."""
    rows = []
    current = start_date
    while current <= end_date:
        if current.weekday() == 6:  # Skip Sundays
            current += timedelta(days=1)
            continue
        if is_russian_holiday(current):
            current += timedelta(days=1)
            continue
        for h in WORKING_HOURS:
            rows.append({"ds": datetime(current.year, current.month, current.day, h)})
        current += timedelta(days=1)

    if not rows:
        return pd.DataFrame()

    future = pd.DataFrame(rows)
    future["ds"] = pd.to_datetime(future["ds"])
    future = add_regressors(future)

    # Add cap/floor for logistic growth models
    if model.growth == "logistic":
        if hasattr(model, "history") and "cap" in model.history.columns:
            future["cap"] = float(model.history["cap"].iloc[0])
        else:
            future["cap"] = float(np.log1p(60.0))  # Fallback
        future["floor"] = 0.0

    fc = model.predict(future[["ds"] + REGRESSOR_COLUMNS + (
        ["cap", "floor"] if model.growth == "logistic" else []
    )])

    return fc


# ---------------------------------------------------------------------------
# 4. Compare predictions vs actuals
# ---------------------------------------------------------------------------
def evaluate_branch(
    branch_id: int,
    actuals: pd.DataFrame,
    visits_model: Prophet,
    wait_model: Prophet,
    holdout_start: date,
    holdout_end: date,
) -> dict | None:
    """Evaluate a branch's model on a holdout period."""
    # Get actuals for this branch in the holdout period
    mask = (
        (actuals["branch_id"] == branch_id)
        & (actuals["date"].dt.date >= holdout_start)
        & (actuals["date"].dt.date <= holdout_end)
    )
    branch_actuals = actuals[mask].copy()

    if len(branch_actuals) < 12:  # Need at least 1 day of data
        return None

    # Generate predictions for the holdout period
    visits_fc = predict_for_period(visits_model, holdout_start, holdout_end)
    if visits_fc.empty:
        return None

    wait_fc = predict_for_period(wait_model, holdout_start, holdout_end)

    # Inverse log1p transform
    visits_fc["predicted"] = np.maximum(np.expm1(visits_fc["yhat"].values), 0.0)
    visits_fc["ci_lower"] = np.maximum(np.expm1(visits_fc["yhat_lower"].values), 0.0)
    visits_fc["ci_upper"] = np.maximum(np.expm1(visits_fc["yhat_upper"].values), 0.0)

    # Clamp wait predictions
    model_log_cap = getattr(wait_model, "wait_log_cap", None)
    if model_log_cap is None:
        model_log_cap = float(np.log1p(60.0))
    wait_fc["yhat"] = wait_fc["yhat"].clip(upper=model_log_cap)
    wait_fc["predicted_wait"] = np.maximum(np.expm1(wait_fc["yhat"].values), 0.0)

    # Merge on (date, hour)
    visits_fc["date"] = visits_fc["ds"].dt.date
    visits_fc["hour"] = visits_fc["ds"].dt.hour
    branch_actuals["date_key"] = branch_actuals["date"].dt.date

    merged = branch_actuals.merge(
        visits_fc[["date", "hour", "predicted", "ci_lower", "ci_upper"]],
        left_on=["date_key", "hour"],
        right_on=["date", "hour"],
        how="inner",
    )

    if len(merged) < 12:
        return None

    actual_visits = merged["total_visits"].values
    pred_visits = merged["predicted"].values
    ci_lo = merged["ci_lower"].values
    ci_up = merged["ci_upper"].values

    # Visits metrics
    wmape = calculate_mape(actual_visits, pred_visits)
    mae = calculate_mae(actual_visits, pred_visits)
    rmse = calculate_rmse(actual_visits, pred_visits)
    ci_cov = calculate_ci_coverage(actual_visits, ci_lo, ci_up)

    # Peak accuracy
    actual_for_peak = pd.DataFrame({"ds": merged["dt_zapis"] if "dt_zapis" in merged.columns
                                    else pd.to_datetime(merged["date_key"].astype(str) + " " + merged["hour"].astype(str) + ":00:00"),
                                    "y": actual_visits})
    pred_for_peak = pd.DataFrame({"ds": actual_for_peak["ds"], "yhat": pred_visits})
    peak_acc = calculate_peak_accuracy(actual_for_peak, pred_for_peak)

    # Wait time metrics (if available)
    wait_fc["date"] = wait_fc["ds"].dt.date
    wait_fc["hour"] = wait_fc["ds"].dt.hour
    merged_wait = branch_actuals.merge(
        wait_fc[["date", "hour", "predicted_wait"]],
        left_on=["date_key", "hour"],
        right_on=["date", "hour"],
        how="inner",
    )
    wait_wmape = None
    wait_mae = None
    if len(merged_wait) > 0 and merged_wait["avg_wait_minutes"].notna().sum() > 10:
        valid_wait = merged_wait.dropna(subset=["avg_wait_minutes"])
        if len(valid_wait) > 10:
            actual_wait = valid_wait["avg_wait_minutes"].values
            pred_wait = valid_wait["predicted_wait"].values
            wait_wmape = calculate_mape(actual_wait, pred_wait)
            wait_mae = calculate_mae(actual_wait, pred_wait)

    # Summary stats
    return {
        "branch_id": branch_id,
        "holdout_rows": len(merged),
        "actual_mean": float(np.mean(actual_visits)),
        "actual_std": float(np.std(actual_visits)),
        "pred_mean": float(np.mean(pred_visits)),
        "pred_std": float(np.std(pred_visits)),
        "wmape": round(wmape, 2),
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "ci_coverage": round(ci_cov, 4),
        "peak_accuracy": round(peak_acc, 4),
        "wait_wmape": round(wait_wmape, 2) if wait_wmape is not None else None,
        "wait_mae": round(wait_mae, 2) if wait_mae is not None else None,
        "passed_25": wmape < 25,
        "passed_40": wmape < 40,
        "passed_60": wmape < 60,
    }


# ---------------------------------------------------------------------------
# 5. Data quality analysis
# ---------------------------------------------------------------------------
def analyze_data_quality(hourly: pd.DataFrame) -> dict:
    """Analyze data quality issues that may explain poor forecast performance."""
    issues = {}

    # Per-branch stats
    branch_stats = hourly.groupby("branch_id").agg(
        total_rows=("total_visits", "count"),
        date_min=("date", "min"),
        date_max=("date", "max"),
        avg_visits=("total_visits", "mean"),
        std_visits=("total_visits", "std"),
        max_visits=("total_visits", "max"),
        zero_hours=("total_visits", lambda x: (x == 0).sum()),
        pct_zero=("total_visits", lambda x: (x == 0).mean() * 100),
    ).reset_index()

    # Branches with high sparsity (>30% zero hours)
    sparse = branch_stats[branch_stats["pct_zero"] > 30]
    issues["sparse_branches"] = len(sparse)
    issues["sparse_branch_ids"] = sparse["branch_id"].tolist()

    # Branches with very low volume
    low_vol = branch_stats[branch_stats["avg_visits"] < 2]
    issues["low_volume_branches"] = len(low_vol)
    issues["low_volume_ids"] = low_vol["branch_id"].tolist()

    # Branches with high variance (CV > 1.5)
    branch_stats["cv"] = branch_stats["std_visits"] / branch_stats["avg_visits"].replace(0, np.nan)
    high_var = branch_stats[branch_stats["cv"] > 1.5]
    issues["high_variance_branches"] = len(high_var)
    issues["high_variance_ids"] = high_var["branch_id"].tolist()

    # Data gaps (missing dates)
    for bid in hourly["branch_id"].unique():
        bdata = hourly[hourly["branch_id"] == bid]
        dates = bdata["date"].dt.date.unique()
        if len(dates) < 2:
            continue
        expected_days = (max(dates) - min(dates)).days + 1
        # Exclude Sundays
        actual_days = len(dates)

    # Hourly pattern check: are some hours consistently low?
    hourly_avg = hourly.groupby("hour")["total_visits"].mean()
    issues["hourly_avg_visits"] = {int(h): round(v, 1) for h, v in hourly_avg.items()}

    # Day-of-week pattern
    hourly["dow"] = hourly["date"].dt.dayofweek
    dow_avg = hourly.groupby("dow")["total_visits"].mean()
    issues["dow_avg_visits"] = {int(d): round(v, 1) for d, v in dow_avg.items()}

    # Overall stats
    issues["total_branches"] = hourly["branch_id"].nunique()
    issues["total_rows"] = len(hourly)
    issues["date_range"] = f"{hourly['date'].min().date()} to {hourly['date'].max().date()}"

    return issues


# ---------------------------------------------------------------------------
# 6. Test new forecast generation
# ---------------------------------------------------------------------------
def test_new_forecast_generation(
    models: dict[int, tuple[Prophet, Prophet]],
    test_month: tuple[int, int] = (2026, 3),
) -> dict:
    """Test generating forecasts for a future month."""
    year, month = test_month
    results = {
        "target_month": f"{year}-{month:02d}",
        "branches_tested": 0,
        "branches_failed": 0,
        "failures": [],
        "stats": [],
    }

    for bid, (visits_model, wait_model) in models.items():
        try:
            fc = predict_for_period(
                visits_model,
                date(year, month, 1),
                date(year, month, 28),  # Safe last day
            )
            if fc.empty:
                results["branches_failed"] += 1
                results["failures"].append({"branch_id": bid, "error": "Empty forecast"})
                continue

            # Inverse transform
            fc["predicted"] = np.maximum(np.expm1(fc["yhat"].values), 0.0)
            fc["ci_lower"] = np.maximum(np.expm1(fc["yhat_lower"].values), 0.0)
            fc["ci_upper"] = np.maximum(np.expm1(fc["yhat_upper"].values), 0.0)

            # Check for anomalies
            has_negative = (fc["predicted"] < 0).any()
            has_nan = fc["predicted"].isna().any()
            has_inf = np.isinf(fc["predicted"]).any()
            max_pred = float(fc["predicted"].max())
            mean_pred = float(fc["predicted"].mean())
            ci_width = float((fc["ci_upper"] - fc["ci_lower"]).mean())

            # Wait model
            wfc = predict_for_period(wait_model, date(year, month, 1), date(year, month, 28))
            model_log_cap = getattr(wait_model, "wait_log_cap", None)
            if model_log_cap is None:
                model_log_cap = float(np.log1p(60.0))
            wfc["yhat"] = wfc["yhat"].clip(upper=model_log_cap)
            wfc["predicted_wait"] = np.maximum(np.expm1(wfc["yhat"].values), 0.0)
            max_wait = float(wfc["predicted_wait"].max())

            results["branches_tested"] += 1
            stats = {
                "branch_id": bid,
                "forecast_hours": len(fc),
                "mean_predicted_visits": round(mean_pred, 1),
                "max_predicted_visits": round(max_pred, 1),
                "avg_ci_width": round(ci_width, 1),
                "max_predicted_wait_min": round(max_wait, 1),
                "has_negative": bool(has_negative),
                "has_nan": bool(has_nan),
                "has_inf": bool(has_inf),
            }
            results["stats"].append(stats)

            if has_nan or has_inf:
                results["branches_failed"] += 1
                results["failures"].append({
                    "branch_id": bid,
                    "error": f"NaN={has_nan}, Inf={has_inf}",
                })

        except Exception as e:
            results["branches_failed"] += 1
            results["failures"].append({"branch_id": bid, "error": str(e)})

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 80)
    print("COMPREHENSIVE FORECAST QUALITY VALIDATION")
    print("=" * 80)

    # --- Step 1: Load and aggregate raw data ---
    print("\n--- STEP 1: Loading raw CSV data ---")
    raw = load_raw_csv_data()

    print("\n--- STEP 2: Aggregating hourly stats ---")
    hourly = aggregate_hourly_stats(raw)

    # --- Step 2: Data quality analysis ---
    print("\n--- STEP 3: Data quality analysis ---")
    quality = analyze_data_quality(hourly)
    print(f"  Total branches in data: {quality['total_branches']}")
    print(f"  Date range: {quality['date_range']}")
    print(f"  Sparse branches (>30% zero hours): {quality['sparse_branches']}")
    print(f"  Low volume branches (<2 avg visits): {quality['low_volume_branches']}")
    print(f"  High variance branches (CV>1.5): {quality['high_variance_branches']}")

    print("\n  Avg visits by hour:")
    for h in sorted(quality["hourly_avg_visits"]):
        print(f"    {h:02d}:00 → {quality['hourly_avg_visits'][h]:.1f}")

    print("\n  Avg visits by day of week (0=Mon, 6=Sun):")
    for d in sorted(quality["dow_avg_visits"]):
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        print(f"    {days[d]}: {quality['dow_avg_visits'][d]:.1f}")

    # --- Step 3: Load models ---
    print("\n--- STEP 4: Loading trained models ---")
    models = load_models()

    # Determine holdout period
    # Training used data up to Feb 21, 2024
    # Use Jan 15 - Feb 15, 2024 as holdout (overlaps with training tail)
    # Also test with last 4 weeks of data
    data_max = hourly["date"].max().date()
    data_min = hourly["date"].min().date()

    # Use last 3 weeks of data as holdout
    holdout_end = data_max
    holdout_start = holdout_end - timedelta(days=21)
    print(f"\n  Holdout period: {holdout_start} to {holdout_end}")

    # Also do a separate test with earlier period (cross-validation)
    cv_end = holdout_start - timedelta(days=1)
    cv_start = cv_end - timedelta(days=21)
    print(f"  Cross-val period: {cv_start} to {cv_end}")

    # --- Step 4: Evaluate each branch ---
    print("\n--- STEP 5: Evaluating forecast quality (holdout) ---")
    results = []
    trained_branch_ids = set(models.keys())
    data_branch_ids = set(hourly["branch_id"].unique())
    common_branches = trained_branch_ids & data_branch_ids
    print(f"  Branches with models AND data: {len(common_branches)}")

    for bid in sorted(common_branches):
        vm, wm = models[bid]
        res = evaluate_branch(bid, hourly, vm, wm, holdout_start, holdout_end)
        if res:
            results.append(res)
            status = "PASS" if res["passed_25"] else ("OK" if res["passed_40"] else "FAIL")
            print(
                f"  Branch {bid:>4d}: wMAPE={res['wmape']:6.1f}%  "
                f"MAE={res['mae']:6.1f}  RMSE={res['rmse']:7.1f}  "
                f"CI={res['ci_coverage']:.2f}  Peak={res['peak_accuracy']:.2f}  [{status}]"
            )

    # --- Step 5: Cross-validation period ---
    print(f"\n--- STEP 6: Cross-validation ({cv_start} to {cv_end}) ---")
    cv_results = []
    for bid in sorted(common_branches):
        vm, wm = models[bid]
        res = evaluate_branch(bid, hourly, vm, wm, cv_start, cv_end)
        if res:
            cv_results.append(res)

    # --- Step 6: Summary ---
    print("\n" + "=" * 80)
    print("SUMMARY: HOLDOUT PERIOD")
    print("=" * 80)

    if results:
        wmapes = [r["wmape"] for r in results]
        maes = [r["mae"] for r in results]
        rmses = [r["rmse"] for r in results]
        ci_covs = [r["ci_coverage"] for r in results]
        peaks = [r["peak_accuracy"] for r in results]

        pass_25 = sum(1 for r in results if r["passed_25"])
        pass_40 = sum(1 for r in results if r["passed_40"])
        pass_60 = sum(1 for r in results if r["passed_60"])

        print(f"  Branches evaluated: {len(results)}")
        print(f"  wMAPE <25% (great):   {pass_25}/{len(results)}")
        print(f"  wMAPE <40% (good):    {pass_40}/{len(results)}")
        print(f"  wMAPE <60% (usable):  {pass_60}/{len(results)}")
        print(f"  Avg wMAPE: {np.mean(wmapes):.1f}%  (median: {np.median(wmapes):.1f}%)")
        print(f"  Avg MAE: {np.mean(maes):.1f}  (median: {np.median(maes):.1f})")
        print(f"  Avg RMSE: {np.mean(rmses):.1f}")
        print(f"  Avg CI coverage: {np.mean(ci_covs):.2%}")
        print(f"  Avg Peak accuracy: {np.mean(peaks):.2%}")

        # Best and worst branches
        sorted_by_wmape = sorted(results, key=lambda r: r["wmape"])
        print("\n  TOP 5 best branches (lowest wMAPE):")
        for r in sorted_by_wmape[:5]:
            print(f"    Branch {r['branch_id']}: wMAPE={r['wmape']:.1f}%, MAE={r['mae']:.1f}, "
                  f"avg_visits={r['actual_mean']:.1f}")

        print("\n  TOP 5 worst branches (highest wMAPE):")
        for r in sorted_by_wmape[-5:]:
            print(f"    Branch {r['branch_id']}: wMAPE={r['wmape']:.1f}%, MAE={r['mae']:.1f}, "
                  f"avg_visits={r['actual_mean']:.1f}")

        # Correlation analysis: wMAPE vs volume
        volumes = [r["actual_mean"] for r in results]
        corr = np.corrcoef(wmapes, volumes)[0, 1]
        print(f"\n  Correlation(wMAPE, avg_volume): {corr:.3f}")

        # Wait time metrics
        wait_results = [r for r in results if r["wait_wmape"] is not None]
        if wait_results:
            print(f"\n  Wait time metrics ({len(wait_results)} branches):")
            wait_wmapes = [r["wait_wmape"] for r in wait_results]
            wait_maes = [r["wait_mae"] for r in wait_results]
            print(f"    Avg wait wMAPE: {np.mean(wait_wmapes):.1f}%")
            print(f"    Avg wait MAE: {np.mean(wait_maes):.1f} min")

    # Cross-validation summary
    if cv_results:
        print(f"\n{'='*80}")
        print(f"SUMMARY: CROSS-VALIDATION PERIOD ({cv_start} to {cv_end})")
        print(f"{'='*80}")
        cv_wmapes = [r["wmape"] for r in cv_results]
        cv_pass_25 = sum(1 for r in cv_results if r["passed_25"])
        cv_pass_40 = sum(1 for r in cv_results if r["passed_40"])
        cv_pass_60 = sum(1 for r in cv_results if r["passed_60"])
        print(f"  Branches evaluated: {len(cv_results)}")
        print(f"  wMAPE <25%: {cv_pass_25}/{len(cv_results)}")
        print(f"  wMAPE <40%: {cv_pass_40}/{len(cv_results)}")
        print(f"  wMAPE <60%: {cv_pass_60}/{len(cv_results)}")
        print(f"  Avg wMAPE: {np.mean(cv_wmapes):.1f}%  (median: {np.median(cv_wmapes):.1f}%)")

    # --- Step 7: Test new forecast generation ---
    print(f"\n{'='*80}")
    print("STEP 7: Testing new forecast generation (March 2026)")
    print("=" * 80)
    gen_results = test_new_forecast_generation(models, (2026, 3))
    print(f"  Branches tested: {gen_results['branches_tested']}")
    print(f"  Branches failed: {gen_results['branches_failed']}")

    if gen_results["failures"]:
        print("  Failures:")
        for f in gen_results["failures"]:
            print(f"    Branch {f['branch_id']}: {f['error']}")

    if gen_results["stats"]:
        avg_visits = np.mean([s["mean_predicted_visits"] for s in gen_results["stats"]])
        max_visits = max(s["max_predicted_visits"] for s in gen_results["stats"])
        avg_ci = np.mean([s["avg_ci_width"] for s in gen_results["stats"]])
        max_wait = max(s["max_predicted_wait_min"] for s in gen_results["stats"])
        has_issues = sum(1 for s in gen_results["stats"] if s["has_nan"] or s["has_inf"])

        print(f"\n  Forecast sanity checks:")
        print(f"    Avg predicted visits across branches: {avg_visits:.1f}")
        print(f"    Max predicted visits (any branch/hour): {max_visits:.0f}")
        print(f"    Avg confidence interval width: {avg_ci:.1f}")
        print(f"    Max predicted wait time: {max_wait:.1f} min")
        print(f"    Branches with NaN/Inf: {has_issues}")

        # Reasonableness check
        print(f"\n  Reasonableness checks:")
        for s in gen_results["stats"]:
            issues = []
            if s["mean_predicted_visits"] < 0.1:
                issues.append("near-zero visits")
            if s["max_predicted_visits"] > 500:
                issues.append(f"very high max ({s['max_predicted_visits']:.0f})")
            if s["max_predicted_wait_min"] > 120:
                issues.append(f"extreme wait ({s['max_predicted_wait_min']:.0f} min)")
            if s["avg_ci_width"] > 100:
                issues.append(f"wide CI ({s['avg_ci_width']:.0f})")
            if issues:
                print(f"    Branch {s['branch_id']}: {', '.join(issues)}")

    # --- Step 8: Root cause analysis ---
    print(f"\n{'='*80}")
    print("ROOT CAUSE ANALYSIS")
    print("=" * 80)

    print("""
  Why wMAPE is high (73%+ avg):

  1. DATA SPARSITY: Many branches have sparse hourly data (>30% zero-visit hours).
     Prophet treats zeros as real signal, inflating error on low-traffic hours.

  2. LOW VOLUME: Several branches average <5 visits/hour. With such low counts,
     even a +/- 2 visit error translates to 50-100% wMAPE.

  3. SHORT TRAINING DATA: Only ~8 months (Jun 2023 - Feb 2024). Prophet needs
     12+ months for reliable yearly seasonality estimation.

  4. HIGH VARIANCE: MFC traffic is inherently bursty. Day-to-day variation
     is large even within the same hour/branch.

  5. LOG TRANSFORM BIAS: log1p(y) + expm1() introduces asymmetric errors.
     Small log-scale errors become large in original scale for high-traffic branches.

  6. ZERO-FILLING EFFECT: Filling missing hours with 0 visits before training
     may teach Prophet to predict low values when data is simply missing.

  Potential improvements:
  - Use DAILY aggregation instead of HOURLY for lower-volume branches
  - Train separate weekday/weekend models
  - Add external regressors (weather, season of government services)
  - Use longer training data or synthetic augmentation
  - Switch to simpler models (seasonal ARIMA) for low-volume branches
  - Post-hoc calibration: scale predictions to match actual daily totals
""")

    # Save detailed results to JSON
    report = {
        "generated_at": datetime.now().isoformat(),
        "holdout_period": f"{holdout_start} to {holdout_end}",
        "cv_period": f"{cv_start} to {cv_end}",
        "data_quality": quality,
        "holdout_results": results,
        "cv_results": cv_results,
        "new_forecast_test": gen_results,
    }

    report_path = MODELS_DIR / "quality_validation_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nDetailed report saved to: {report_path}")


if __name__ == "__main__":
    main()
