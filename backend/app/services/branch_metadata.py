"""Валидация и синхронизация метаданных филиалов."""

from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from app.models import Branch, HourlyStat, QueueRecord
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)


class BranchMetadataValidator:
    """Валидация метаданных филиалов."""

    def __init__(self, db: Session):
        self.db = db

    def get_window_count_from_history(self, branch_id: int) -> Optional[Dict]:
        """
        Извлекает количество окон из исторических данных.

        Args:
            branch_id: ID филиала

        Returns:
            Dict с max_windows, avg_windows, data_points или None
        """
        # Из hourly_stats
        hourly_stats = self.db.query(
            func.max(HourlyStat.num_windows_active).label('max_windows'),
            func.avg(HourlyStat.num_windows_active).label('avg_windows'),
            func.count(HourlyStat.id).label('data_points')
        ).filter(
            HourlyStat.branch_id == branch_id,
            HourlyStat.num_windows_active > 0
        ).first()

        if not hourly_stats or not hourly_stats.max_windows:
            # Fallback: из queue_records
            queue_stats = self.db.query(
                func.count(distinct(QueueRecord.employee_window)).label('unique_windows')
            ).filter(
                QueueRecord.branch_id == branch_id,
                QueueRecord.employee_window.isnot(None)
            ).first()

            if queue_stats and queue_stats.unique_windows:
                return {
                    'max_windows': queue_stats.unique_windows,
                    'avg_windows': queue_stats.unique_windows,
                    'data_points': 1,
                    'source': 'queue_records'
                }

            return None

        return {
            'max_windows': int(hourly_stats.max_windows),
            'avg_windows': float(hourly_stats.avg_windows),
            'data_points': int(hourly_stats.data_points),
            'source': 'hourly_stats'
        }
