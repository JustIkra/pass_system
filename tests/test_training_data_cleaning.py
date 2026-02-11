"""Edge case tests for training data cleaning and preparation.

Tests outlier detection, zero-filling, log transform edge cases,
and data sufficiency checks in prepare_training_data().
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import Base, Branch, HourlyStat
from backend.app.ml.training import prepare_training_data, MIN_DATA_POINTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    """Create in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def branch_normal(db_session):
    """Branch with normal 30-day data."""
    branch = Branch(id=200, name="Normal Branch")
    db_session.add(branch)

    for day in range(30):
        for hour in range(8, 20):
            stat = HourlyStat(
                branch_id=200,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=np.random.randint(40, 80),
                avg_wait_seconds=np.random.uniform(300, 900),
            )
            db_session.add(stat)

    db_session.commit()
    return branch


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------

def test_prepare_data_insufficient_points(db_session):
    """
    Edge case: Branch has fewer than MIN_DATA_POINTS.

    Expected: Return empty DataFrame or DataFrame with insufficient flag.
    """
    # ARRANGE: Branch with only 10 days (120 points < 360 needed)
    branch = Branch(id=201, name="Insufficient Data")
    db_session.add(branch)

    for day in range(10):  # Only 10 days
        for hour in range(8, 20):
            stat = HourlyStat(
                branch_id=201,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=50,
            )
            db_session.add(stat)

    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 201, target="total_visits")

    # ASSERT: Should track original count
    original_count = df.attrs.get("original_count", len(df))

    # Original count should be 10 days * 12 hours = 120
    assert original_count == 120, f"Expected 120 original points, got {original_count}"

    # This is less than MIN_DATA_POINTS (360)
    assert original_count < MIN_DATA_POINTS, \
        "Should be flagged as insufficient data"

    # Note: The caller (train_all_models) checks original_count and skips this branch


def test_prepare_data_no_data(db_session):
    """
    Edge case: Branch has no hourly_stats at all.

    Expected: Return empty DataFrame.
    """
    # ARRANGE: Empty branch
    branch = Branch(id=202, name="Empty Branch")
    db_session.add(branch)
    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 202, target="total_visits")

    # ASSERT
    assert df.empty, "Should return empty DataFrame for branch with no data"


def test_prepare_data_all_outliers_wait_time(db_session):
    """
    Edge case: All wait times are extreme outliers.

    Expected: All values clipped to P95 (which would be the minimum in this case).
    """
    # ARRANGE: Branch with all extreme wait times
    branch = Branch(id=203, name="All Outliers Wait")
    db_session.add(branch)

    # All wait times are extreme (2+ hours)
    for day in range(30):
        for hour in range(8, 20):
            stat = HourlyStat(
                branch_id=203,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=50,
                avg_wait_seconds=7200,  # 2 hours (extreme)
            )
            db_session.add(stat)

    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 203, target="avg_wait_minutes")

    # ASSERT: All values should be clipped
    # P95 of all-same values = that value, so clipping happens at 120 min
    # Then log1p transform: log1p(120) ≈ 4.8
    assert not df.empty, "Should return data"
    assert df['y'].min() >= 0, "All values should be non-negative after log1p"

    # After inverse transform, max should be around 120 min (P95 clip point)
    max_wait_log = df['y'].max()
    max_wait_original = np.expm1(max_wait_log)

    # Since all values are clipped to P95=120, max should be ~120
    assert 100 <= max_wait_original <= 130, \
        f"Expected P95 clip around 120 min, got {max_wait_original:.1f}"


def test_prepare_data_iqr_equals_zero(db_session):
    """
    Edge case: IQR = 0 (all values identical).

    Expected: No outlier removal (std fallback), return all data.
    """
    # ARRANGE: Branch with constant visits
    branch = Branch(id=204, name="Constant Visits")
    db_session.add(branch)

    for day in range(30):
        for hour in range(8, 20):
            stat = HourlyStat(
                branch_id=204,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=60,  # Always 60
            )
            db_session.add(stat)

    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 204, target="total_visits")

    # ASSERT: All data retained (no outliers when IQR=0)
    original_count = df.attrs.get("original_count", 0)
    assert original_count == 30 * 12, "Should have all 360 original points"

    # After zero-fill (which fills Sunday gaps), we should have more points
    assert len(df) >= original_count, "Zero-fill should preserve or add points"

    # All y values should be log1p(60) after transform
    expected_y = np.log1p(60)
    assert np.allclose(df['y'], expected_y, atol=0.01), \
        f"All y values should be log1p(60)={expected_y:.2f}"


def test_prepare_data_zero_visits_hours(db_session):
    """
    Edge case: Some hours have 0 visits (branch closed early?).

    Expected: Zero values preserved, not treated as outliers.
    """
    # ARRANGE: Branch with some zero-visit hours
    branch = Branch(id=205, name="Sparse Hours")
    db_session.add(branch)

    for day in range(30):
        for hour in range(8, 20):
            # Hours 8-9 and 18-19 have zero visits (closed early?)
            if hour in [8, 9, 18, 19]:
                visits = 0
            else:
                visits = np.random.randint(40, 80)

            stat = HourlyStat(
                branch_id=205,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=visits,
            )
            db_session.add(stat)

    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 205, target="total_visits")

    # ASSERT: Zero visits should be preserved
    # log1p(0) = 0, so we should have some y=0 values
    zero_count = (df['y'] == 0).sum()
    assert zero_count > 0, "Zero visits should be preserved as y=0"

    # Should have zeros for hours 8,9,18,19 across 30 days = 4 hours * 30 days = 120 zeros
    # (plus any zero-filled Sunday gaps)
    assert zero_count >= 120, f"Expected at least 120 zeros, got {zero_count}"


def test_prepare_data_single_extreme_outlier_wait(db_session, branch_normal):
    """
    Edge case: Single extreme wait time outlier among normal values.

    Expected: Outlier clipped to P95, not removed.
    """
    # ARRANGE: Add one extreme outlier
    extreme_stat = HourlyStat(
        branch_id=200,
        date=date(2024, 2, 1),
        hour=10,
        total_visits=50,
        avg_wait_seconds=28000,  # 467 minutes (extreme, actual max from data)
    )
    db_session.add(extreme_stat)
    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 200, target="avg_wait_minutes")

    # ASSERT: Outlier should be clipped to P95
    # Normal wait times: 5-15 min (300-900 sec)
    # P95 of normal data: ~15 min
    # Extreme outlier: 467 min -> clipped to P95

    max_wait_log = df['y'].max()
    max_wait_original = np.expm1(max_wait_log)

    # Should be clipped to around P95 (~15-20 min range)
    assert max_wait_original < 30, \
        f"Extreme outlier not clipped: {max_wait_original:.1f} min (expected <30)"


def test_prepare_data_missing_hourly_slots(db_session):
    """
    Edge case: Historical data has gaps (missing hours/days).

    Expected: Zero-fill gaps to create complete grid.
    """
    # ARRANGE: Branch with missing data (only odd days, only hours 10-14)
    branch = Branch(id=206, name="Sparse Data")
    db_session.add(branch)

    for day in range(1, 30, 2):  # Only odd days
        for hour in range(10, 15):  # Only 5 hours (10-14)
            stat = HourlyStat(
                branch_id=206,
                date=date(2024, 1, day),
                hour=hour,
                total_visits=50,
            )
            db_session.add(stat)

    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 206, target="total_visits")

    # ASSERT: Should zero-fill missing slots
    original_count = df.attrs.get("original_count", 0)

    # Original: 15 days * 5 hours = 75 points
    assert original_count == 75, f"Expected 75 original points, got {original_count}"

    # After zero-fill: should have (30 days - ~4 Sundays) * 12 hours ≈ 312 points
    # (Sundays are skipped in zero-fill)
    assert len(df) > original_count, \
        f"Zero-fill should add points: {len(df)} vs original {original_count}"

    # Many points should be zero (filled gaps)
    zero_count = (df['y'] == 0).sum()
    expected_zeros = len(df) - original_count  # Filled gaps
    assert zero_count >= expected_zeros * 0.8, \
        f"Expected ~{expected_zeros} zeros from fill, got {zero_count}"


def test_prepare_data_sunday_skipped(db_session):
    """
    Edge case: Zero-fill should skip Sundays (MFC closed).

    Expected: No data points for Sundays in final DataFrame.
    """
    # ARRANGE: Branch with full week data including Sundays
    branch = Branch(id=207, name="Full Week Branch")
    db_session.add(branch)

    # Add 4 weeks of data including Sundays
    for day in range(28):  # 4 weeks
        current_date = date(2024, 1, 1 + day)
        for hour in range(8, 20):
            stat = HourlyStat(
                branch_id=207,
                date=current_date,
                hour=hour,
                total_visits=50,
            )
            db_session.add(stat)

    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 207, target="total_visits")

    # ASSERT: No Sundays in output
    df['ds'] = pd.to_datetime(df['ds'])
    sundays = df[df['ds'].dt.dayofweek == 6]

    assert len(sundays) == 0, \
        f"Found {len(sundays)} Sunday data points (should be 0)"


def test_prepare_data_log_transform_applied(db_session, branch_normal):
    """
    Edge case: Verify log1p transform is correctly applied.

    Expected: y values are in log scale, can be inverted with expm1.
    """
    # ACT
    df = prepare_training_data(db_session, 200, target="total_visits")

    # ASSERT: Check log transform
    assert not df.empty, "Should have data"

    # Pick a non-zero y value
    non_zero = df[df['y'] > 0]
    assert len(non_zero) > 0, "Should have non-zero values"

    y_log = non_zero.iloc[0]['y']
    y_original = np.expm1(y_log)

    # Original visits should be in range 40-80 (from fixture)
    assert 30 <= y_original <= 90, \
        f"Inverse transform gave unrealistic value: {y_original}"

    # Log transform should compress range
    # log1p(40) ≈ 3.7, log1p(80) ≈ 4.4
    assert 3.0 <= y_log <= 5.0, \
        f"Log-scale value out of expected range: {y_log}"


def test_prepare_data_wait_cap_stored(db_session, branch_normal):
    """
    Edge case: Wait model should store log_cap in DataFrame attrs.

    Expected: df.attrs['log_cap'] exists for wait target.
    """
    # ACT
    df = prepare_training_data(db_session, 200, target="avg_wait_minutes")

    # ASSERT: log_cap should be stored
    assert 'log_cap' in df.attrs, \
        "Wait model should store log_cap in DataFrame attrs"

    log_cap = df.attrs['log_cap']
    assert log_cap > 0, f"log_cap should be positive: {log_cap}"

    # Cap should be log1p(P95 * 2.0)
    # For normal wait times (5-15 min), P95 ≈ 15, so cap ≈ log1p(30) ≈ 3.4
    assert 2.0 <= log_cap <= 5.0, \
        f"log_cap out of expected range: {log_cap}"


def test_prepare_data_regressors_added(db_session, branch_normal):
    """
    Edge case: Verify all regressors are added to DataFrame.

    Expected: DataFrame has all REGRESSOR_COLUMNS.
    """
    from backend.app.ml.utils import REGRESSOR_COLUMNS

    # ACT
    df = prepare_training_data(db_session, 200, target="total_visits")

    # ASSERT: All regressors present
    for regressor in REGRESSOR_COLUMNS:
        assert regressor in df.columns, \
            f"Missing regressor column: {regressor}"

    # Check regressor values are binary (0 or 1)
    for regressor in REGRESSOR_COLUMNS:
        unique_vals = df[regressor].unique()
        assert set(unique_vals).issubset({0, 1}), \
            f"Regressor {regressor} has non-binary values: {unique_vals}"


def test_prepare_data_original_count_tracked(db_session, branch_normal):
    """
    Edge case: original_count attribute tracks pre-zero-fill row count.

    Expected: df.attrs['original_count'] <= len(df) after zero-fill.
    """
    # ACT
    df = prepare_training_data(db_session, 200, target="total_visits")

    # ASSERT
    original_count = df.attrs.get("original_count", 0)
    assert original_count > 0, "original_count should be tracked"

    # After zero-fill, final length should be >= original
    assert len(df) >= original_count, \
        f"Zero-fill should not reduce row count: {len(df)} < {original_count}"


def test_prepare_data_null_wait_time_handling(db_session):
    """
    Edge case: Some hours have NULL avg_wait_minutes.

    Expected: Null values converted to 0.0.
    """
    # ARRANGE: Branch with some null wait times
    branch = Branch(id=208, name="Null Wait Times")
    db_session.add(branch)

    for day in range(30):
        for hour in range(8, 20):
            # Some hours have null wait time
            wait_seconds = None if hour in [8, 19] else np.random.uniform(300, 900)

            stat = HourlyStat(
                branch_id=208,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=50,
                avg_wait_seconds=wait_seconds,
            )
            db_session.add(stat)

    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 208, target="avg_wait_minutes")

    # ASSERT: No NaN values in y column
    assert not df['y'].isna().any(), "Should not have NaN values in y"

    # Null wait times should be converted to 0 (log1p(0) = 0)
    zero_count = (df['y'] == 0).sum()
    assert zero_count > 0, "Null wait times should be converted to 0"
