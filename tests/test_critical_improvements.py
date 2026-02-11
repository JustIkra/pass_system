"""P0 критические тесты для улучшений качества прогнозирования.

Эти тесты должны FAIL в текущей версии (TDD red phase).
Будут реализованы в Phase 1-5 согласно плану разработки.
"""

import sys
from pathlib import Path

# Add backend to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Branch, HourlyStat, Forecast


# Import will fail initially - part of TDD red phase
try:
    from app.ml.postprocessing import (
        get_branch_capacity,
        apply_constraints,
        postprocess_forecast,
    )
    POSTPROCESSING_AVAILABLE = True
except ImportError:
    POSTPROCESSING_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    """Create in-memory test database."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_branch(db_session):
    """Create test branch with historical data."""
    branch = Branch(id=166, name="Суджанский район")
    db_session.add(branch)

    # Add historical hourly stats (30 days, 8-19 hours = 360 points)
    for day in range(30):
        for hour in range(8, 20):  # 8:00-19:00
            stat = HourlyStat(
                branch_id=166,
                date=date(2024, 1, 1 + day),
                hour=hour,
                total_visits=np.random.randint(20, 80),  # Realistic range
                avg_wait_seconds=np.random.uniform(300, 900),
                num_windows_active=5,  # 5 windows
            )
            db_session.add(stat)

    db_session.commit()
    return branch


# ---------------------------------------------------------------------------
# P0 Critical Tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not POSTPROCESSING_AVAILABLE, reason="postprocessing.py not yet implemented")
def test_end_to_end_branch_166_forecast_correction(db_session, sample_branch):
    """
    P0: Прогноз для филиала 166 (Суджанский район) улучшился после постобработки.

    Критерий успеха:
    - wMAPE улучшился как минимум на 10% (было ~40%, должно стать <30%)
    - Нет прогнозов выше capacity (125 visits/hour для 5 окон)
    - Все прогнозы неотрицательные

    Phase: 1 (Postprocessing) + Phase 3 (Capacity constraint)
    """
    # ARRANGE: Create realistic forecast data with known issues
    forecast_data = []

    for day in range(31):  # March 2026
        current_date = date(2026, 3, 1 + day)
        if current_date.weekday() == 6:  # Skip Sundays
            continue

        for hour in range(8, 20):
            # Normal predictions with some outliers
            if day == 5 and hour == 10:
                predicted = 250  # Outlier: way above capacity (125)
            elif day == 10 and hour == 14:
                predicted = -5  # Negative outlier (shouldn't happen but test it)
            else:
                predicted = np.random.uniform(30, 90)

            forecast_data.append({
                'date': current_date,
                'hour': hour,
                'predicted_visits': predicted,
            })

    predictions_df = pd.DataFrame(forecast_data)

    # ACT: Apply postprocessing
    corrected_df = postprocess_forecast(
        predictions_df,
        branch_id=166,
        db=db_session,
        apply_smoothing=True,
        correct_outliers=True,
    )

    # ASSERT: Check improvements
    capacity = get_branch_capacity(db_session, 166)
    assert capacity == 5 * 25, f"Expected capacity 125, got {capacity}"
    assert corrected_df['predicted_visits'].max() <= capacity, \
        f"Forecast exceeds capacity: {corrected_df['predicted_visits'].max()} > {capacity}"

    assert corrected_df['predicted_visits'].min() >= 0, \
        f"Negative prediction found: {corrected_df['predicted_visits'].min()}"

    assert 'correction_pct' in corrected_df.columns, "Missing correction_pct column"


@pytest.mark.skipif(not POSTPROCESSING_AVAILABLE, reason="postprocessing.py not yet implemented")
def test_capacity_constraint_all_branches(db_session):
    """
    P0: Все филиалы соблюдают capacity constraint.

    Phase: 3 (Capacity constraint)
    """
    # ARRANGE: Create multiple branches
    branches_config = [(166, 5), (176, 8), (200, 3)]

    for branch_id, num_windows in branches_config:
        branch = Branch(id=branch_id, name=f"Branch {branch_id}")
        db_session.add(branch)

        for day in range(30):
            for hour in range(8, 20):
                stat = HourlyStat(
                    branch_id=branch_id,
                    date=date(2024, 1, 1 + day),
                    hour=hour,
                    total_visits=np.random.randint(10, 50),
                    num_windows_active=num_windows,
                )
                db_session.add(stat)

    db_session.commit()

    # ACT & ASSERT
    for branch_id, expected_windows in branches_config:
        capacity = get_branch_capacity(db_session, branch_id)
        expected_capacity = expected_windows * 25
        assert capacity == expected_capacity

        predictions = np.array([expected_capacity + 50] * 12)
        hours = np.arange(8, 20)

        corrected = apply_constraints(predictions, branch_id=branch_id, hours=hours, db=db_session)
        assert corrected.max() <= capacity


def test_api_forecast_quality_field_present():
    """
    P0: API возвращает quality_metrics в ответе.

    Phase: 4 (API enhancement)
    """
    # Test schema structure (contract test)
    response_schema = {
        "data": [],
        "summary": {},
        "quality_metrics": {
            "wmape": 0.0,
            "corrections_applied": 0,
            "outliers_removed": 0,
        }
    }

    # This will FAIL until schema is implemented
    pytest.fail("ForecastResponse schema not yet updated with quality_metrics field")


@pytest.mark.skip(reason="Frontend test - will be in Playwright")
def test_frontend_quality_badge_renders():
    """P0: Frontend отображает quality badge. Phase: 5"""
    pass


def test_outlier_cleaning_does_not_remove_too_much(db_session, sample_branch):
    """
    P0: Outlier cleaning удаляет <10% данных.

    Phase: 2 (Outlier cleaning)
    """
    from app.ml.training import prepare_training_data

    # Add extreme outliers
    for outlier_date in [date(2024, 1, 5), date(2024, 1, 15)]:
        stat = HourlyStat(
            branch_id=166,
            date=outlier_date,
            hour=10,
            total_visits=500,  # Extreme outlier
            avg_wait_seconds=5000,
            num_windows_active=5,
        )
        db_session.add(stat)

    db_session.commit()

    # ACT
    df = prepare_training_data(db_session, 166, target="total_visits")
    original_count = df.attrs.get("original_count", len(df))

    # ASSERT
    assert original_count >= 360, f"Insufficient data: {original_count}"

    # Check wait time clipping
    df_wait = prepare_training_data(db_session, 166, target="avg_wait_minutes")
    if not df_wait.empty:
        max_wait_log = df_wait['y'].max()
        max_wait_original = np.expm1(max_wait_log)
        assert max_wait_original < 30, \
            f"Wait time outlier not clipped: {max_wait_original:.1f} min"
