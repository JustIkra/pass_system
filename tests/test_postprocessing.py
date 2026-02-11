"""Edge case tests for postprocessing module.

Tests boundary conditions, error handling, and edge cases
for capacity constraints, smoothing, and outlier detection.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import Base, Branch, HourlyStat
from backend.app.ml.postprocessing import (
    get_branch_capacity,
    get_historical_bounds,
    get_hourly_bounds,
    apply_constraints,
    smooth_predictions,
    detect_outliers_in_predictions,
    postprocess_forecast,
)


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
def branch_with_data(db_session):
    """Branch with 30 days of hourly stats."""
    branch = Branch(id=100, name="Test Branch")
    db_session.add(branch)

    for day in range(30):
        for hour in range(8, 20):
            stat = HourlyStat(
                branch_id=100,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=np.random.randint(30, 70),
                num_windows_active=5,
            )
            db_session.add(stat)

    db_session.commit()
    return branch


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------

def test_capacity_zero_windows(db_session):
    """
    Edge case: Branch has no active windows in history.

    Expected: Fallback to max_visits * 1.2 as capacity.
    """
    # ARRANGE: Branch with zero windows but some visits
    branch = Branch(id=101, name="No Windows Branch")
    db_session.add(branch)

    # Historical data with num_windows_active = 0 (data entry error?)
    for day in range(10):
        stat = HourlyStat(
            branch_id=101,
            date=date(2024, 1, 1 + day),
            hour=10,
            total_visits=50,
            num_windows_active=0,  # Zero windows!
        )
        db_session.add(stat)

    db_session.commit()

    # ACT
    capacity = get_branch_capacity(db_session, 101)

    # ASSERT: Should fallback to max_visits * 1.2
    expected = 50 * 1.2
    assert capacity == expected, \
        f"Expected fallback capacity {expected}, got {capacity}"


def test_capacity_no_data(db_session):
    """
    Edge case: Branch has no historical data at all.

    Expected: Return default capacity (100).
    """
    # ARRANGE: Empty branch
    branch = Branch(id=102, name="Empty Branch")
    db_session.add(branch)
    db_session.commit()

    # ACT
    capacity = get_branch_capacity(db_session, 102)

    # ASSERT: Should return default value
    assert capacity == 100, f"Expected default capacity 100, got {capacity}"


def test_historical_bounds_zero_variance(db_session):
    """
    Edge case: All historical visits are identical (std = 0).

    Expected: Should not crash, return reasonable bounds.
    """
    # ARRANGE: Branch with constant visits
    branch = Branch(id=103, name="Constant Branch")
    db_session.add(branch)

    for day in range(20):
        for hour in range(8, 20):
            stat = HourlyStat(
                branch_id=103,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=50,  # Always 50
                num_windows_active=3,
            )
            db_session.add(stat)

    db_session.commit()

    # ACT
    lower, upper = get_historical_bounds(db_session, 103, confidence=3.0)

    # ASSERT: When std=0, fallback to mean * 0.5 for std calculation
    # lower = max(0, 50 - 3 * 25) = 0
    # upper = 50 + 3 * 25 = 125
    assert lower >= 0, f"Lower bound negative: {lower}"
    assert upper >= lower, f"Upper < lower: {upper} < {lower}"
    assert upper > 0, f"Upper bound should be positive: {upper}"


def test_hourly_bounds_no_data_for_hour(db_session):
    """
    Edge case: No historical data for specific hour.

    Expected: Fallback to general historical bounds.
    """
    # ARRANGE: Branch with data only for hours 9-11
    branch = Branch(id=104, name="Sparse Hours Branch")
    db_session.add(branch)

    for day in range(20):
        for hour in [9, 10, 11]:  # Only 3 hours
            stat = HourlyStat(
                branch_id=104,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=40,
                num_windows_active=4,
            )
            db_session.add(stat)

    db_session.commit()

    # ACT: Request bounds for hour that has no data (hour=15)
    lower, upper = get_hourly_bounds(db_session, 104, hour=15)

    # ASSERT: Should return fallback bounds (not crash)
    assert lower >= 0, f"Negative lower bound: {lower}"
    assert upper >= lower, f"Upper < lower: {upper} < {lower}"


def test_apply_constraints_empty_predictions(db_session, branch_with_data):
    """
    Edge case: Empty predictions array.

    Expected: Return empty array without crashing.
    """
    # ARRANGE
    predictions = np.array([])
    hours = np.array([])

    # ACT
    result = apply_constraints(
        predictions,
        branch_id=100,
        hours=hours,
        db=db_session,
        use_hourly=True,
    )

    # ASSERT
    assert len(result) == 0, f"Expected empty result, got {len(result)} elements"
    assert isinstance(result, np.ndarray), "Should return numpy array"


def test_smooth_predictions_insufficient_data():
    """
    Edge case: Predictions array shorter than smoothing window.

    Expected: Return original predictions unmodified.
    """
    # ARRANGE: Only 2 points, window=3
    predictions = np.array([10.0, 20.0])

    # ACT
    smoothed = smooth_predictions(predictions, window=3)

    # ASSERT: Should return original
    np.testing.assert_array_equal(smoothed, predictions,
                                   "Should not smooth when len < window")


def test_smooth_predictions_preserves_edges():
    """
    Edge case: Smoothing should preserve edge values.

    Expected: First and last values unchanged after smoothing.
    """
    # ARRANGE: Clear signal with spike in middle
    predictions = np.array([50.0, 50.0, 50.0, 200.0, 50.0, 50.0, 50.0])

    # ACT
    smoothed = smooth_predictions(predictions, window=3)

    # ASSERT: Edges should be preserved
    assert smoothed[0] == predictions[0], \
        f"First value changed: {smoothed[0]} != {predictions[0]}"
    assert smoothed[-1] == predictions[-1], \
        f"Last value changed: {smoothed[-1]} != {predictions[-1]}"

    # Middle spike should be reduced by averaging
    assert smoothed[3] < predictions[3], \
        "Spike should be smoothed down"


def test_detect_outliers_constant_predictions():
    """
    Edge case: All predictions identical (std=0).

    Expected: No outliers detected (return all False).
    """
    # ARRANGE: Constant predictions
    predictions = np.array([50.0] * 20)

    # ACT
    outliers = detect_outliers_in_predictions(predictions, threshold=3.0)

    # ASSERT: All False (no outliers)
    assert not outliers.any(), "Constant values should have no outliers"
    assert len(outliers) == len(predictions), "Output length mismatch"


def test_detect_outliers_single_extreme():
    """
    Edge case: One extreme outlier among normal values.

    Expected: Only the extreme value flagged as outlier.
    """
    # ARRANGE: Normal values + one extreme
    predictions = np.array([50.0, 52.0, 48.0, 51.0, 49.0, 500.0, 50.0, 51.0])

    # ACT
    outliers = detect_outliers_in_predictions(predictions, threshold=3.0)

    # ASSERT: Only position 5 (value=500) should be True
    assert outliers[5] == True, "Extreme value not detected as outlier"
    assert outliers.sum() == 1, f"Expected 1 outlier, found {outliers.sum()}"


def test_detect_outliers_too_few_points():
    """
    Edge case: Fewer than 3 points.

    Expected: Return all False (can't detect outliers with <3 points).
    """
    # ARRANGE
    predictions = np.array([10.0, 20.0])

    # ACT
    outliers = detect_outliers_in_predictions(predictions, threshold=3.0)

    # ASSERT: All False
    assert not outliers.any(), "Should not detect outliers with <3 points"
    assert len(outliers) == 2, "Output length mismatch"


def test_postprocess_empty_dataframe(db_session, branch_with_data):
    """
    Edge case: Empty predictions DataFrame.

    Expected: Return empty DataFrame without crashing.
    """
    # ARRANGE
    empty_df = pd.DataFrame(columns=['date', 'hour', 'predicted_visits'])

    # ACT
    result = postprocess_forecast(
        empty_df,
        branch_id=100,
        db=db_session,
        apply_smoothing=True,
        correct_outliers=True,
    )

    # ASSERT
    assert len(result) == 0, f"Expected empty result, got {len(result)} rows"
    assert isinstance(result, pd.DataFrame), "Should return DataFrame"


def test_postprocess_single_point(db_session, branch_with_data):
    """
    Edge case: Single prediction point.

    Expected: Process without crashing, no smoothing/outlier detection.
    """
    # ARRANGE
    df = pd.DataFrame([{
        'date': date(2026, 3, 1),
        'hour': 10,
        'predicted_visits': 60.0,
    }])

    # ACT
    result = postprocess_forecast(
        df,
        branch_id=100,
        db=db_session,
        apply_smoothing=True,
        correct_outliers=True,
    )

    # ASSERT
    assert len(result) == 1, f"Expected 1 row, got {len(result)}"
    assert result.iloc[0]['predicted_visits'] >= 0, "Prediction should be non-negative"
    assert result.iloc[0]['predicted_visits'] <= get_branch_capacity(db_session, 100), \
        "Prediction should respect capacity"


def test_postprocess_all_outliers(db_session, branch_with_data):
    """
    Edge case: All predictions are outliers.

    Expected: Should handle gracefully (interpolate or clip to bounds).
    """
    # ARRANGE: All predictions are extreme outliers
    capacity = get_branch_capacity(db_session, 100)  # Should be 125
    df = pd.DataFrame([
        {'date': date(2026, 3, 1 + i), 'hour': 10, 'predicted_visits': capacity * 3}
        for i in range(10)
    ])

    # ACT
    result = postprocess_forecast(
        df,
        branch_id=100,
        db=db_session,
        apply_smoothing=True,
        correct_outliers=True,
    )

    # ASSERT: All should be clipped to capacity
    assert result['predicted_visits'].max() <= capacity, \
        f"Outliers not clipped: max={result['predicted_visits'].max()} > capacity={capacity}"


def test_postprocess_missing_metadata(db_session):
    """
    Edge case: Branch has no metadata (no historical stats).

    Expected: Use fallback values, don't crash.
    """
    # ARRANGE: Branch with no historical data
    branch = Branch(id=999, name="No History Branch")
    db_session.add(branch)
    db_session.commit()

    df = pd.DataFrame([
        {'date': date(2026, 3, 1), 'hour': 10, 'predicted_visits': 80.0},
        {'date': date(2026, 3, 1), 'hour': 11, 'predicted_visits': 85.0},
    ])

    # ACT
    result = postprocess_forecast(
        df,
        branch_id=999,
        db=db_session,
        apply_smoothing=False,
        correct_outliers=False,
    )

    # ASSERT: Should use fallback capacity (100)
    assert len(result) == 2, "Should process both rows"
    assert result['predicted_visits'].max() <= 100, \
        "Should use default capacity fallback"


def test_postprocess_negative_predictions(db_session, branch_with_data):
    """
    Edge case: Some predictions are negative (shouldn't happen but test it).

    Expected: Clip to 0.
    """
    # ARRANGE
    df = pd.DataFrame([
        {'date': date(2026, 3, 1), 'hour': 10, 'predicted_visits': -10.0},
        {'date': date(2026, 3, 1), 'hour': 11, 'predicted_visits': 50.0},
        {'date': date(2026, 3, 1), 'hour': 12, 'predicted_visits': -5.0},
    ])

    # ACT
    result = postprocess_forecast(
        df,
        branch_id=100,
        db=db_session,
        apply_smoothing=False,
        correct_outliers=False,
    )

    # ASSERT: All should be non-negative
    assert result['predicted_visits'].min() >= 0, \
        f"Negative values not clipped: min={result['predicted_visits'].min()}"


def test_postprocess_correction_pct_calculation(db_session, branch_with_data):
    """
    Edge case: Verify correction_pct is calculated correctly.

    Expected: correction_pct = (new - old) / old * 100
    """
    # ARRANGE: Predictions that will be corrected
    capacity = get_branch_capacity(db_session, 100)
    df = pd.DataFrame([
        {'date': date(2026, 3, 1), 'hour': 10, 'predicted_visits': capacity * 2},
    ])

    # ACT
    result = postprocess_forecast(
        df,
        branch_id=100,
        db=db_session,
        apply_smoothing=False,
        correct_outliers=False,
    )

    # ASSERT: Check correction_pct
    original = result['predicted_visits_original'].iloc[0]
    corrected = result['predicted_visits'].iloc[0]
    expected_pct = (corrected - original) / original * 100

    actual_pct = result['correction_pct'].iloc[0]

    assert abs(actual_pct - expected_pct) < 0.01, \
        f"correction_pct mismatch: {actual_pct:.2f} != {expected_pct:.2f}"
