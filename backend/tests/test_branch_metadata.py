# tests/test_branch_metadata.py
import pytest
from app.services.branch_metadata import BranchMetadataValidator
from app.database import SessionLocal

def test_extract_window_count_from_history():
    """Извлечение количества окон из исторических данных."""
    db = SessionLocal()
    validator = BranchMetadataValidator(db)

    # Branch ID 12 - известный филиал с данными
    result = validator.get_window_count_from_history(branch_id=12)

    assert result is not None
    assert result['max_windows'] > 0
    assert result['avg_windows'] > 0
    assert result['data_points'] > 100  # Достаточно данных

    db.close()
