"""Test suite for MFC Forecast Dashboard.

Structure:
- test_critical_improvements.py - P0 критические тесты (TDD red phase)
- test_postprocessing.py - Edge cases для постобработки прогнозов
- test_training_data_cleaning.py - Edge cases для подготовки данных

Run all tests:
    pytest tests/

Run specific test file:
    pytest tests/test_critical_improvements.py

Run with coverage:
    pytest --cov=backend/app tests/

Run only P0 tests:
    pytest -m "not skip" tests/test_critical_improvements.py
"""
