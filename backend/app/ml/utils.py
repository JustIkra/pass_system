"""Utility functions for ML module: holidays, regressors, metrics."""

from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Russian public holidays
# ---------------------------------------------------------------------------

_FIXED_HOLIDAYS: list[tuple[int, int, str]] = [
    (1, 1, "Новогодние каникулы"),
    (1, 2, "Новогодние каникулы"),
    (1, 3, "Новогодние каникулы"),
    (1, 4, "Новогодние каникулы"),
    (1, 5, "Новогодние каникулы"),
    (1, 6, "Новогодние каникулы"),
    (1, 7, "Рождество Христово"),
    (1, 8, "Новогодние каникулы"),
    (2, 23, "День защитника Отечества"),
    (3, 8, "Международный женский день"),
    (5, 1, "Праздник Весны и Труда"),
    (5, 9, "День Победы"),
    (6, 12, "День России"),
    (11, 4, "День народного единства"),
]


def parse_russian_holidays(year: int) -> list[dict[str, Any]]:
    """Return Russian public holidays for *year* in Prophet format.

    Each entry is ``{"holiday": <name>, "ds": <date string>, "lower_window": 0,
    "upper_window": 0}``.
    """
    holidays: list[dict[str, Any]] = []
    for month, day, name in _FIXED_HOLIDAYS:
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        holidays.append(
            {
                "holiday": name,
                "ds": d.isoformat(),
                "lower_window": 0,
                "upper_window": 0,
            }
        )
    return holidays


def get_russian_holidays_df(years: list[int] | None = None) -> pd.DataFrame:
    """Build a holidays DataFrame spanning *years* (default 2023-2027).

    The returned DataFrame has columns ``holiday`` and ``ds`` as expected by
    :pymod:`prophet`.
    """
    if years is None:
        years = list(range(2023, 2028))
    rows: list[dict[str, Any]] = []
    for y in years:
        rows.extend(parse_russian_holidays(y))
    df = pd.DataFrame(rows)
    df["ds"] = pd.to_datetime(df["ds"])
    return df


def is_russian_holiday(d: date) -> bool:
    """Return ``True`` if *d* is a Russian public holiday."""
    for month, day, _ in _FIXED_HOLIDAYS:
        if d.month == month and d.day == day:
            return True
    return False


# ---------------------------------------------------------------------------
# Regressors
# ---------------------------------------------------------------------------

REGRESSOR_COLUMNS: list[str] = [
    "is_month_start",
    "is_month_end",
    "is_monday",
    "is_weekend",
    "is_friday",
]


def add_regressors(df: pd.DataFrame) -> pd.DataFrame:
    """Add regressor columns to a DataFrame that already has a ``ds`` column.

    Columns added:
    * ``is_month_start`` -- 1 if day of month is in [1, 5], else 0
    * ``is_month_end``   -- 1 if day is within last 3 days of its month, else 0
    * ``is_monday``      -- 1 if Monday, else 0
    * ``is_weekend``     -- 1 if Saturday (weekday=5), else 0
    * ``is_friday``      -- 1 if Friday (weekday=4), else 0
    """
    df = df.copy()
    ds = pd.to_datetime(df["ds"])

    df["is_month_start"] = (ds.dt.day <= 5).astype(int)

    last_day_of_month = ds.apply(
        lambda x: calendar.monthrange(x.year, x.month)[1]
    )
    df["is_month_end"] = ((last_day_of_month - ds.dt.day) < 3).astype(int)

    df["is_monday"] = (ds.dt.dayofweek == 0).astype(int)
    df["is_weekend"] = (ds.dt.dayofweek == 5).astype(int)
    df["is_friday"] = (ds.dt.dayofweek == 4).astype(int)

    return df


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def calculate_mape(actual: np.ndarray | pd.Series, predicted: np.ndarray | pd.Series) -> float:
    """Weighted Mean Absolute Percentage Error (wMAPE).

    wMAPE = sum(|actual - predicted|) / sum(actual) * 100

    More robust than standard MAPE: weights errors by traffic volume,
    so low-visit hours don't dominate the metric.

    Returns percentage value (e.g. 15.3 means 15.3 %).
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    total = np.sum(actual)
    if total == 0:
        return 0.0
    return float(np.sum(np.abs(actual - predicted)) / total * 100)


def calculate_mae(actual: np.ndarray | pd.Series, predicted: np.ndarray | pd.Series) -> float:
    """Mean Absolute Error."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.mean(np.abs(actual - predicted)))


def calculate_rmse(actual: np.ndarray | pd.Series, predicted: np.ndarray | pd.Series) -> float:
    """Root Mean Squared Error."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def calculate_peak_accuracy(
    actual_df: pd.DataFrame,
    predicted_df: pd.DataFrame,
    top_n: int = 3,
) -> float:
    """Fraction of weeks where top-N peak hours match between actual and predicted.

    Both DataFrames must have columns ``ds`` (datetime) and ``y`` (or ``yhat``
    for *predicted_df*).

    The metric is defined as the fraction of weeks in which at least
    ``ceil(top_n * 2 / 3)`` of the top-N hours (by value) coincide between
    actual and predicted.
    """
    actual_col = "y" if "y" in actual_df.columns else "yhat"
    predicted_col = "yhat" if "yhat" in predicted_df.columns else "y"

    a = actual_df[["ds", actual_col]].copy()
    p = predicted_df[["ds", predicted_col]].copy()

    a["ds"] = pd.to_datetime(a["ds"])
    p["ds"] = pd.to_datetime(p["ds"])

    a["week"] = a["ds"].dt.isocalendar().week.astype(int)
    a["year"] = a["ds"].dt.year
    p["week"] = p["ds"].dt.isocalendar().week.astype(int)
    p["year"] = p["ds"].dt.year

    # Use (year, week) as grouping key to avoid week-number collision across years
    a["yw"] = a["year"].astype(str) + "_" + a["week"].astype(str)
    p["yw"] = p["year"].astype(str) + "_" + p["week"].astype(str)

    common_weeks = set(a["yw"].unique()) & set(p["yw"].unique())
    if not common_weeks:
        return 0.0

    threshold = int(np.ceil(top_n * 2 / 3))
    matches = 0
    total = 0

    for yw in common_weeks:
        a_week = a[a["yw"] == yw]
        p_week = p[p["yw"] == yw]
        if len(a_week) < top_n or len(p_week) < top_n:
            continue

        top_actual_hours = set(
            a_week.nlargest(top_n, actual_col)["ds"].dt.hour.tolist()
        )
        top_pred_hours = set(
            p_week.nlargest(top_n, predicted_col)["ds"].dt.hour.tolist()
        )

        overlap = len(top_actual_hours & top_pred_hours)
        if overlap >= threshold:
            matches += 1
        total += 1

    if total == 0:
        return 0.0
    return float(matches / total)


def calculate_ci_coverage(
    actual: np.ndarray | pd.Series,
    lower: np.ndarray | pd.Series,
    upper: np.ndarray | pd.Series,
) -> float:
    """Fraction of actual values within [lower, upper] confidence interval."""
    actual = np.asarray(actual, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if len(actual) == 0:
        return 0.0
    within = ((actual >= lower) & (actual <= upper)).sum()
    return float(within / len(actual))
