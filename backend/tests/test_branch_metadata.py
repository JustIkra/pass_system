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


def test_store_validated_metadata():
    """Сохранение валидированных метаданных филиала."""
    db = SessionLocal()
    validator = BranchMetadataValidator(db)

    metadata = {
        'branch_id': 12,
        'num_windows': 51,
        'source': 'hourly_stats',
        'validated_at': '2026-02-10',
        'confidence': 'high'
    }

    result = validator.store_metadata(metadata)
    assert result is True

    # Проверяем что сохранилось
    stored = validator.get_metadata(branch_id=12)
    assert stored['num_windows'] == 51

    db.close()
