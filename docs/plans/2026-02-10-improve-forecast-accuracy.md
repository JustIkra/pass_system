# Улучшение точности прогнозов МФЦ - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Повысить качество прогнозов с 33% до 70% филиалов с ошибкой <25%, устранив проблемы завышенных прогнозов (Суджанский район +1665%, МФЦ №1 +288%)

**Architecture:** Трехуровневый подход: (1) очистка и валидация метаданных филиалов (количество окон), (2) постобработка прогнозов с capacity constraints и статистическими границами, (3) очистка обучающих данных от outliers и переобучение проблемных моделей

**Tech Stack:** Prophet, NumPy, Pandas, SQLAlchemy, pytest

**Current State:**
- 166 моделей Prophet обучены
- 67% филиалов имеют ошибку >50%
- Критические филиалы: ID 166 (Суджанский, +1665%), ID 12 (МФЦ №1, +288%)
- Проблема: количество окон в филиалах различается между источниками данных

---

## Phase 1: Валидация и синхронизация метаданных филиалов

### Task 1.1: Создать модуль валидации метаданных

**Files:**
- Create: `backend/app/services/branch_metadata.py`
- Create: `tests/test_branch_metadata.py`

**Step 1: Write failing test for window count extraction**

```python
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
```

**Step 2: Run test to verify it fails**

```bash
cd backend
pytest tests/test_branch_metadata.py::test_extract_window_count_from_history -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.branch_metadata'`

**Step 3: Implement window count extraction**

```python
# backend/app/services/branch_metadata.py
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
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_branch_metadata.py::test_extract_window_count_from_history -v
```

Expected: `PASSED`

**Step 5: Commit**

```bash
git add backend/app/services/branch_metadata.py tests/test_branch_metadata.py
git commit -m "feat: add window count extraction from historical data"
```

---

### Task 1.2: Добавить таблицу для хранения валидированных метаданных

**Files:**
- Modify: `backend/app/models.py` (add BranchMetadata model)
- Create: `backend/alembic/versions/001_add_branch_metadata.py`

**Step 1: Write failing test for metadata storage**

```python
# tests/test_branch_metadata.py
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
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_branch_metadata.py::test_store_validated_metadata -v
```

Expected: `AttributeError: 'BranchMetadataValidator' object has no attribute 'store_metadata'`

**Step 3: Add BranchMetadata model**

```python
# backend/app/models.py (add after Forecast class)

class BranchMetadata(Base):
    """Валидированные метаданные филиалов."""

    __tablename__ = "branch_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("branches.id"), nullable=False, unique=True
    )
    num_windows: Mapped[int] = mapped_column(Integer, nullable=False)
    num_windows_source: Mapped[str] = mapped_column(String, nullable=False)  # hourly_stats | queue_records | manual
    capacity_per_window: Mapped[int] = mapped_column(Integer, default=25)  # клиентов/окно/час
    max_capacity: Mapped[int] = mapped_column(Integer, nullable=False)  # num_windows * capacity_per_window

    validated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    confidence: Mapped[str] = mapped_column(String, nullable=False)  # high | medium | low
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    branch: Mapped["Branch"] = relationship(back_populates="metadata")

# Add to Branch model:
# metadata: Mapped["BranchMetadata | None"] = relationship(back_populates="branch", uselist=False)
```

**Step 4: Implement store_metadata and get_metadata**

```python
# backend/app/services/branch_metadata.py

from app.models import BranchMetadata
from datetime import datetime

class BranchMetadataValidator:
    # ... existing code ...

    def store_metadata(self, metadata: Dict) -> bool:
        """
        Сохраняет валидированные метаданные.

        Args:
            metadata: Dict с полями branch_id, num_windows, source, confidence

        Returns:
            True если успешно
        """
        try:
            # Проверяем существует ли запись
            existing = self.db.query(BranchMetadata).filter(
                BranchMetadata.branch_id == metadata['branch_id']
            ).first()

            if existing:
                # Обновляем
                existing.num_windows = metadata['num_windows']
                existing.num_windows_source = metadata['source']
                existing.max_capacity = metadata['num_windows'] * 25
                existing.validated_at = datetime.utcnow()
                existing.confidence = metadata.get('confidence', 'medium')
            else:
                # Создаем новую запись
                new_metadata = BranchMetadata(
                    branch_id=metadata['branch_id'],
                    num_windows=metadata['num_windows'],
                    num_windows_source=metadata['source'],
                    max_capacity=metadata['num_windows'] * 25,
                    confidence=metadata.get('confidence', 'medium')
                )
                self.db.add(new_metadata)

            self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Error storing metadata for branch {metadata['branch_id']}: {e}")
            self.db.rollback()
            return False

    def get_metadata(self, branch_id: int) -> Optional[Dict]:
        """
        Получает валидированные метаданные филиала.

        Args:
            branch_id: ID филиала

        Returns:
            Dict с метаданными или None
        """
        metadata = self.db.query(BranchMetadata).filter(
            BranchMetadata.branch_id == branch_id
        ).first()

        if not metadata:
            return None

        return {
            'branch_id': metadata.branch_id,
            'num_windows': metadata.num_windows,
            'source': metadata.num_windows_source,
            'capacity_per_window': metadata.capacity_per_window,
            'max_capacity': metadata.max_capacity,
            'validated_at': metadata.validated_at.isoformat(),
            'confidence': metadata.confidence
        }
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_branch_metadata.py::test_store_validated_metadata -v
```

Expected: `PASSED`

**Step 6: Create migration**

```bash
cd backend
alembic revision -m "add branch_metadata table"
```

Edit generated migration file to add table creation.

**Step 7: Run migration**

```bash
alembic upgrade head
```

**Step 8: Commit**

```bash
git add backend/app/models.py backend/app/services/branch_metadata.py tests/test_branch_metadata.py backend/alembic/versions/
git commit -m "feat: add branch_metadata table for validated window counts"
```

---

### Task 1.3: Создать скрипт валидации и синхронизации

**Files:**
- Create: `scripts/validate_branch_metadata.py`
- Create: `docs/BRANCH_METADATA_DISCREPANCIES.md`

**Step 1: Write validation script**

```python
# scripts/validate_branch_metadata.py
#!/usr/bin/env python3
"""
Валидация и синхронизация метаданных филиалов.

Проблема: количество окон различается между источниками:
- hourly_stats.num_windows_active
- COUNT(DISTINCT queue_records.employee_window)
- Информация с сайтов МФЦ

Этот скрипт:
1. Извлекает данные из всех источников
2. Выявляет расхождения
3. Сохраняет валидированные значения
"""

import sys
sys.path.insert(0, 'backend')

from app.database import SessionLocal
from app.services.branch_metadata import BranchMetadataValidator
from app.models import Branch
import pandas as pd


def validate_all_branches():
    """Валидирует метаданные для всех филиалов."""
    db = SessionLocal()
    validator = BranchMetadataValidator(db)

    branches = db.query(Branch).all()

    print(f"{'Branch ID':<12} | {'Name':<50} | {'Windows':<10} | {'Source':<15} | {'Confidence':<12}")
    print("-" * 110)

    discrepancies = []

    for branch in branches:
        # Извлекаем из истории
        history_data = validator.get_window_count_from_history(branch.id)

        if not history_data:
            print(f"{branch.id:<12} | {branch.name[:48]:<50} | {'N/A':<10} | {'No data':<15} | {'N/A':<12}")
            continue

        # Определяем уровень доверия
        if history_data['data_points'] > 1000:
            confidence = 'high'
        elif history_data['data_points'] > 100:
            confidence = 'medium'
        else:
            confidence = 'low'

        num_windows = int(history_data['max_windows'])

        print(f"{branch.id:<12} | {branch.name[:48]:<50} | {num_windows:<10} | {history_data['source']:<15} | {confidence:<12}")

        # Сохраняем
        metadata = {
            'branch_id': branch.id,
            'num_windows': num_windows,
            'source': history_data['source'],
            'confidence': confidence
        }
        validator.store_metadata(metadata)

        # Если есть расхождения между источниками - добавляем в отчет
        if history_data['source'] == 'hourly_stats':
            avg_windows = history_data['avg_windows']
            if abs(num_windows - avg_windows) > 5:  # Расхождение >5 окон
                discrepancies.append({
                    'branch_id': branch.id,
                    'name': branch.name,
                    'max_windows': num_windows,
                    'avg_windows': avg_windows,
                    'difference': num_windows - avg_windows
                })

    db.close()

    # Генерируем отчет о расхождениях
    if discrepancies:
        generate_discrepancy_report(discrepancies)

    print(f"\n✅ Валидация завершена. Обработано {len(branches)} филиалов.")
    if discrepancies:
        print(f"⚠️  Найдено {len(discrepancies)} филиалов с расхождениями в количестве окон.")
        print(f"   См. отчет: docs/BRANCH_METADATA_DISCREPANCIES.md")


def generate_discrepancy_report(discrepancies):
    """Генерирует отчет о расхождениях."""
    with open('docs/BRANCH_METADATA_DISCREPANCIES.md', 'w', encoding='utf-8') as f:
        f.write("# Расхождения в количестве окон филиалов\n\n")
        f.write(f"**Дата:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## Филиалы с расхождениями\n\n")
        f.write("| Branch ID | Название | Max окон | Avg окон | Разница |\n")
        f.write("|-----------|----------|----------|----------|----------|\n")

        for item in sorted(discrepancies, key=lambda x: abs(x['difference']), reverse=True):
            f.write(f"| {item['branch_id']} | {item['name'][:40]} | {item['max_windows']} | {item['avg_windows']:.1f} | {item['difference']:.1f} |\n")

        f.write("\n## Рекомендации\n\n")
        f.write("1. **Проверить вручную** количество окон на сайтах филиалов\n")
        f.write("2. **Обновить метаданные** для филиалов с большими расхождениями (>10 окон)\n")
        f.write("3. **Использовать validated metadata** при расчете capacity constraints\n\n")
        f.write("### Обновление метаданных вручную\n\n")
        f.write("```python\n")
        f.write("from app.services.branch_metadata import BranchMetadataValidator\n")
        f.write("validator = BranchMetadataValidator(db)\n")
        f.write("validator.store_metadata({\n")
        f.write("    'branch_id': 166,\n")
        f.write("    'num_windows': 12,  # Проверенное значение\n")
        f.write("    'source': 'manual',\n")
        f.write("    'confidence': 'high'\n")
        f.write("})\n")
        f.write("```\n")


if __name__ == "__main__":
    validate_all_branches()
```

**Step 2: Run validation script**

```bash
python3 scripts/validate_branch_metadata.py
```

Expected: Таблица со всеми филиалами + создание `docs/BRANCH_METADATA_DISCREPANCIES.md`

**Step 3: Review discrepancies**

```bash
cat docs/BRANCH_METADATA_DISCREPANCIES.md
```

Manually verify window counts for branches with large discrepancies using official MFC websites.

**Step 4: Commit**

```bash
git add scripts/validate_branch_metadata.py docs/BRANCH_METADATA_DISCREPANCIES.md
git commit -m "feat: add branch metadata validation script and discrepancy report"
```

---

## Phase 2: Постобработка прогнозов

### Task 2.1: Внедрить capacity constraints

**Files:**
- Already created: `backend/app/ml/postprocessing.py`
- Modify: `backend/app/ml/prediction.py`
- Create: `tests/test_postprocessing.py`

**Step 1: Write failing test for capacity constraints**

```python
# tests/test_postprocessing.py
import pytest
import numpy as np
from app.ml.postprocessing import apply_constraints, get_branch_capacity
from app.database import SessionLocal


def test_apply_capacity_constraints():
    """Прогнозы не должны превышать физическую пропускную способность."""
    db = SessionLocal()

    # Суджанский район (ID 166) - проблемный филиал
    branch_id = 166

    # Симулируем завышенные прогнозы
    predictions = np.array([500.0, 550.0, 600.0])  # Нереально высокие
    hours = np.array([10, 11, 12])

    corrected = apply_constraints(predictions, branch_id, hours, db)

    capacity = get_branch_capacity(db, branch_id)

    # Все прогнозы должны быть <= capacity
    assert np.all(corrected <= capacity)
    assert np.all(corrected < predictions)  # Были скорректированы вниз

    db.close()
```

**Step 2: Run test to verify it passes**

(Код postprocessing.py уже создан выше, тест должен пройти)

```bash
cd backend
pytest tests/test_postprocessing.py::test_apply_capacity_constraints -v
```

Expected: `PASSED`

**Step 3: Integrate postprocessing into prediction pipeline**

```python
# backend/app/ml/prediction.py
# Add after imports:
from app.ml.postprocessing import postprocess_forecast
import pandas as pd


# Modify generate_forecast function (around line 80-100):
def generate_forecast(
    branch_id: int,
    forecast_month: str,
    db: Session,
    apply_postprocessing: bool = True  # NEW parameter
) -> List[Dict]:
    """
    Generates forecast for specified month.

    Args:
        branch_id: Branch ID
        forecast_month: Month in YYYY-MM format
        db: Database session
        apply_postprocessing: Apply capacity constraints and bounds

    Returns:
        List of forecast records
    """
    # ... existing code for loading model and generating forecast ...

    # After expm1 transformation (around line 120):
    forecast_df['predicted_visits'] = np.maximum(
        np.expm1(forecast_df['yhat']), 0.0
    )

    # NEW: Apply postprocessing
    if apply_postprocessing:
        forecast_df = postprocess_forecast(
            forecast_df,
            branch_id,
            db,
            apply_smoothing=True,
            correct_outliers=True
        )

    # ... rest of function ...
    return forecast_records
```

**Step 4: Test integration**

```bash
# Run forecast generation for problematic branch
python3 scripts/generate_forecast.py --branch-id 166 --month 2026-03
```

Expected: Прогнозы для филиала 166 должны быть значительно ниже (не >500/час)

**Step 5: Commit**

```bash
git add backend/app/ml/postprocessing.py backend/app/ml/prediction.py tests/test_postprocessing.py
git commit -m "feat: integrate capacity constraints into forecast pipeline"
```

---

### Task 2.2: Добавить визуализацию эффекта постобработки

**Files:**
- Create: `scripts/visualize_postprocessing_effect.py`

**Step 1: Create visualization script**

```python
# scripts/visualize_postprocessing_effect.py
#!/usr/bin/env python3
"""Визуализация эффекта постобработки на проблемных филиалах."""

import sys
sys.path.insert(0, 'backend')

import matplotlib.pyplot as plt
import numpy as np
from app.database import SessionLocal
from app.models import Forecast, HourlyStat, Branch
from sqlalchemy import func


def visualize_branch(branch_id: int, output_file: str = None):
    """Визуализирует оригинальные и скорректированные прогнозы."""
    db = SessionLocal()

    # Получаем название филиала
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    branch_name = branch.name if branch else f"Branch {branch_id}"

    # Получаем прогнозы (предполагаем что есть predicted_visits_original)
    forecasts = db.query(Forecast).filter(
        Forecast.branch_id == branch_id
    ).order_by(Forecast.date, Forecast.hour).limit(100).all()

    if not forecasts:
        print(f"No forecasts found for branch {branch_id}")
        return

    # Получаем исторические средние по часам
    historical = {}
    for hour in range(8, 20):
        avg = db.query(func.avg(HourlyStat.total_visits)).filter(
            HourlyStat.branch_id == branch_id,
            HourlyStat.hour == hour
        ).scalar()
        historical[hour] = avg if avg else 0

    # Подготовка данных для графика
    hours = [f.hour for f in forecasts]
    predicted = [f.predicted_visits for f in forecasts]
    hist_avgs = [historical.get(h, 0) for h in hours]

    # Создаем график
    fig, ax = plt.subplots(figsize=(14, 6))

    x = range(len(hours))
    ax.plot(x, predicted, label='Прогноз (с постобработкой)', color='#2E86AB', linewidth=2)
    ax.plot(x, hist_avgs, label='Исторические средние', color='#A23B72', linestyle='--', linewidth=2)

    ax.fill_between(x, 0, predicted, alpha=0.2, color='#2E86AB')

    ax.set_xlabel('Час дня', fontsize=12)
    ax.set_ylabel('Количество обращений', fontsize=12)
    ax.set_title(f'{branch_name}\nСравнение прогнозов с историей', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)

    # Настраиваем x-axis
    unique_hours = sorted(set(hours))
    ax.set_xticks([hours.index(h) for h in unique_hours])
    ax.set_xticklabels([f"{h}:00" for h in unique_hours], rotation=45)

    plt.tight_layout()

    if output_file:
        plt.savefig(output_file, dpi=150)
        print(f"Saved to {output_file}")
    else:
        plt.show()

    db.close()


if __name__ == "__main__":
    # Визуализируем проблемные филиалы
    problematic = [166, 12]  # Суджанский, МФЦ №1

    for branch_id in problematic:
        output = f"docs/forecast_visualization_branch_{branch_id}.png"
        visualize_branch(branch_id, output)
```

**Step 2: Run visualization**

```bash
pip install matplotlib
python3 scripts/visualize_postprocessing_effect.py
```

Expected: Создание PNG файлов с графиками в `docs/`

**Step 3: Commit**

```bash
git add scripts/visualize_postprocessing_effect.py docs/forecast_visualization_*.png
git commit -m "feat: add postprocessing effect visualization"
```

---

## Phase 3: Очистка обучающих данных и переобучение

### Task 3.1: Добавить детектирование outliers в обучающие данные

**Files:**
- Modify: `backend/app/ml/training.py`
- Create: `tests/test_training_data_cleaning.py`

**Step 1: Write test for outlier detection**

```python
# tests/test_training_data_cleaning.py
import pytest
import pandas as pd
import numpy as np
from app.ml.training import detect_and_remove_outliers


def test_detect_outliers():
    """Детектирование выбросов в обучающих данных."""
    # Создаем тестовый датасет с выбросом
    data = pd.DataFrame({
        'ds': pd.date_range('2023-01-01', periods=100, freq='H'),
        'y': [10, 12, 11, 13, 15, 14] * 16 + [500, 11, 12, 13]  # 500 = outlier
    })

    cleaned, outliers = detect_and_remove_outliers(data, threshold=3.0)

    assert len(outliers) > 0  # Должен найти outlier
    assert 500 in outliers['y'].values  # Должен найти именно 500
    assert len(cleaned) < len(data)  # Должен удалить outliers
    assert 500 not in cleaned['y'].values  # 500 должно быть удалено


def test_no_outliers():
    """Данные без выбросов не изменяются."""
    data = pd.DataFrame({
        'ds': pd.date_range('2023-01-01', periods=50, freq='H'),
        'y': [10, 12, 11, 13, 15, 14] * 8 + [10, 12]
    })

    cleaned, outliers = detect_and_remove_outliers(data, threshold=3.0)

    assert len(outliers) == 0
    assert len(cleaned) == len(data)
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_training_data_cleaning.py::test_detect_outliers -v
```

Expected: `AttributeError: module 'app.ml.training' has no attribute 'detect_and_remove_outliers'`

**Step 3: Implement outlier detection**

```python
# backend/app/ml/training.py
# Add after imports:

def detect_and_remove_outliers(
    df: pd.DataFrame,
    threshold: float = 3.0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Детектирует и удаляет статистические выбросы из обучающих данных.

    Использует метод IQR (Interquartile Range):
    - Outlier если y < Q1 - threshold*IQR или y > Q3 + threshold*IQR

    Args:
        df: DataFrame с колонками ds, y
        threshold: Множитель для IQR (3.0 = очень консервативный)

    Returns:
        (cleaned_df, outliers_df)
    """
    if len(df) < 10:
        return df, pd.DataFrame()

    Q1 = df['y'].quantile(0.25)
    Q3 = df['y'].quantile(0.75)
    IQR = Q3 - Q1

    lower_bound = Q1 - threshold * IQR
    upper_bound = Q3 + threshold * IQR

    # Находим outliers
    outlier_mask = (df['y'] < lower_bound) | (df['y'] > upper_bound)
    outliers = df[outlier_mask].copy()
    cleaned = df[~outlier_mask].copy()

    if len(outliers) > 0:
        logger.info(f"Removed {len(outliers)} outliers ({len(outliers)/len(df)*100:.1f}%)")
        logger.info(f"  Range: {lower_bound:.1f} - {upper_bound:.1f}")
        logger.info(f"  Outlier values: {outliers['y'].min():.1f} - {outliers['y'].max():.1f}")

    return cleaned, outliers


# Modify train_model function:
def train_model(
    branch_id: int,
    validate: bool = True,
    clean_outliers: bool = True,  # NEW parameter
    outlier_threshold: float = 3.0
) -> Dict[str, Any]:
    """
    Trains Prophet model for a branch.

    Args:
        branch_id: Branch ID
        validate: Run validation
        clean_outliers: Remove outliers from training data
        outlier_threshold: IQR threshold (3.0 default)

    Returns:
        Training results dict
    """
    # ... existing data preparation code ...

    # After prepare_training_data, before log1p:
    if clean_outliers and len(training_data) > 0:
        original_size = len(training_data)
        training_data, outliers = detect_and_remove_outliers(
            training_data,
            threshold=outlier_threshold
        )

        if len(outliers) > 0:
            logger.warning(
                f"Branch {branch_id}: Removed {len(outliers)} outliers "
                f"({len(outliers)/original_size*100:.1f}%)"
            )

    # ... rest of training code ...
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_training_data_cleaning.py -v
```

Expected: `PASSED`

**Step 5: Commit**

```bash
git add backend/app/ml/training.py tests/test_training_data_cleaning.py
git commit -m "feat: add outlier detection and removal in training data"
```

---

### Task 3.2: Переобучить проблемные филиалы

**Files:**
- Create: `scripts/retrain_problematic_branches.py`

**Step 1: Create retraining script**

```python
# scripts/retrain_problematic_branches.py
#!/usr/bin/env python3
"""Переобучение моделей для филиалов с плохими прогнозами."""

import sys
sys.path.insert(0, 'backend')

from app.ml.training import train_model
from app.database import SessionLocal
from app.models import Branch
from sqlalchemy import func, text
import pandas as pd


def identify_problematic_branches(error_threshold: float = 100.0):
    """
    Находит филиалы с ошибкой прогноза >threshold%.

    Args:
        error_threshold: Порог ошибки в процентах

    Returns:
        List of branch IDs
    """
    db = SessionLocal()

    # Запрос для расчета средней ошибки по филиалу
    query = text("""
        WITH historical_avg AS (
            SELECT
                branch_id,
                AVG(total_visits) as hist_avg
            FROM hourly_stats
            WHERE total_visits > 0
            GROUP BY branch_id
        ),
        forecast_avg AS (
            SELECT
                branch_id,
                AVG(predicted_visits) as pred_avg
            FROM forecasts
            GROUP BY branch_id
        )
        SELECT
            h.branch_id,
            b.name,
            h.hist_avg,
            f.pred_avg,
            ABS(h.hist_avg - f.pred_avg) / NULLIF(h.hist_avg, 0) * 100 as error_pct
        FROM historical_avg h
        INNER JOIN forecast_avg f ON h.branch_id = f.branch_id
        INNER JOIN branches b ON h.branch_id = b.id
        WHERE ABS(h.hist_avg - f.pred_avg) / NULLIF(h.hist_avg, 0) * 100 > :threshold
        ORDER BY error_pct DESC
    """)

    result = db.execute(query, {'threshold': error_threshold})
    problematic = result.fetchall()

    db.close()

    return [(row.branch_id, row.name, row.error_pct) for row in problematic]


def retrain_branch(branch_id: int, branch_name: str):
    """Переобучает модель для одного филиала."""
    print(f"\n{'='*80}")
    print(f"Переобучение: {branch_name} (ID: {branch_id})")
    print(f"{'='*80}")

    result = train_model(
        branch_id=branch_id,
        validate=True,
        clean_outliers=True,  # ВАЖНО: очищаем outliers
        outlier_threshold=3.0
    )

    if result['success']:
        print(f"✅ Модель успешно обучена")
        print(f"   wMAPE: {result.get('wmape', 'N/A'):.2f}%")
    else:
        print(f"❌ Ошибка обучения: {result.get('error', 'Unknown')}")

    return result


if __name__ == "__main__":
    print("Поиск филиалов с плохими прогнозами (ошибка >100%)...")

    problematic = identify_problematic_branches(error_threshold=100.0)

    if not problematic:
        print("✅ Не найдено филиалов с критическими ошибками")
        sys.exit(0)

    print(f"\nНайдено {len(problematic)} филиалов:")
    for branch_id, name, error in problematic:
        print(f"  {branch_id:3d}. {name[:50]:<50} - ошибка {error:6.1f}%")

    # Переобучаем
    print(f"\nНачинаем переобучение...")

    results = []
    for branch_id, name, error in problematic:
        result = retrain_branch(branch_id, name)
        results.append({
            'branch_id': branch_id,
            'name': name,
            'old_error': error,
            'success': result['success'],
            'new_wmape': result.get('wmape', None)
        })

    # Итоговый отчет
    print(f"\n{'='*80}")
    print("ИТОГИ ПЕРЕОБУЧЕНИЯ")
    print(f"{'='*80}\n")

    successful = sum(1 for r in results if r['success'])
    print(f"Успешно: {successful}/{len(results)}")

    print(f"\n{'Branch':<50} | {'Старая ошибка':>15} | {'Новая wMAPE':>15}")
    print("-" * 85)
    for r in results:
        if r['success'] and r['new_wmape']:
            print(f"{r['name'][:48]:<50} | {r['old_error']:14.1f}% | {r['new_wmape']:14.1f}%")
        else:
            print(f"{r['name'][:48]:<50} | {r['old_error']:14.1f}% | {'FAILED':>15}")
```

**Step 2: Run retraining**

```bash
python3 scripts/retrain_problematic_branches.py
```

Expected: Список проблемных филиалов + переобучение с очисткой outliers

**Step 3: Commit**

```bash
git add scripts/retrain_problematic_branches.py
git commit -m "feat: add script to retrain problematic branches with outlier cleaning"
```

---

## Phase 4: Валидация улучшений

### Task 4.1: Запустить полную валидацию после улучшений

**Files:**
- Modify: `scripts/comprehensive_data_analysis.py`
- Create: `docs/IMPROVEMENT_REPORT.md`

**Step 1: Run comprehensive analysis**

```bash
python3 scripts/comprehensive_data_analysis.py > docs/IMPROVEMENT_REPORT.md
```

**Step 2: Compare with baseline**

Compare new metrics with original `АНАЛИЗ_ПРОГНОЗОВ.md`:
- % филиалов с ошибкой <25%: было 33% → цель 70%
- Средняя ошибка: было 161.4% → ожидается <50%
- Проблемные филиалы (Суджанский, МФЦ №1): были +1665%, +288% → ожидается <100%

**Step 3: Create improvement summary**

```bash
# Generate summary report
cat << 'EOF' > docs/IMPROVEMENT_SUMMARY.md
# Итоги улучшения прогнозов МФЦ

## Baseline (до улучшений)

- Филиалов с хорошими прогнозами (<25% ошибки): **33%**
- Средняя относительная ошибка: **161.4%**
- Критические филиалы:
  - Суджанский район (ID 166): **+1665%**
  - МФЦ №1 Курск (ID 12): **+288%**

## After improvements

- Филиалов с хорошими прогнозами: **[TO BE FILLED]**
- Средняя относительная ошибка: **[TO BE FILLED]**
- Критические филиалы:
  - Суджанский район: **[TO BE FILLED]**
  - МФЦ №1 Курск: **[TO BE FILLED]**

## Implemented improvements

1. ✅ Валидация и синхронизация метаданных филиалов (количество окон)
2. ✅ Capacity constraints (ограничение пропускной способности)
3. ✅ Статистические границы (mean ± 3σ) по часам
4. ✅ Детектирование и удаление outliers из обучающих данных
5. ✅ Переобучение проблемных моделей
6. ✅ Сглаживание прогнозов

## Next steps

- [ ] Настроить мониторинг качества прогнозов
- [ ] Добавить A/B тестирование
- [ ] Реализовать автоматическое переобучение при деградации
EOF
```

**Step 4: Commit**

```bash
git add docs/IMPROVEMENT_REPORT.md docs/IMPROVEMENT_SUMMARY.md
git commit -m "docs: add improvement validation report"
```

---

## Phase 5: Интеграция в production

### Task 5.1: Обновить API для использования валидированных метаданных

**Files:**
- Modify: `backend/app/api/forecast.py`
- Modify: `backend/app/services/forecast_service.py`

**Step 1: Update forecast service to use validated metadata**

```python
# backend/app/services/forecast_service.py
# Add import
from app.services.branch_metadata import BranchMetadataValidator

class ForecastService:
    def __init__(self, db: Session):
        self.db = db
        self.metadata_validator = BranchMetadataValidator(db)

    def get_forecast_quality(self, branch_id: int) -> str:
        """
        Возвращает качество прогноза для филиала.

        Returns:
            'high' | 'medium' | 'low' | 'unavailable'
        """
        metadata = self.metadata_validator.get_metadata(branch_id)

        if not metadata:
            return 'unavailable'

        return metadata.get('confidence', 'medium')

    # Add to existing get_branch_forecast:
    def get_branch_forecast(self, branch_id: int, month: str):
        # ... existing code ...

        # Add quality indicator
        forecast_data['quality'] = self.get_forecast_quality(branch_id)

        # If quality is low, add warning
        if forecast_data['quality'] == 'low':
            forecast_data['warning'] = (
                'Прогноз может быть неточным из-за недостаточного количества исторических данных'
            )

        return forecast_data
```

**Step 2: Update API response schema**

```python
# backend/app/schemas.py
# Add to BranchForecastResponse:

class BranchForecastResponse(BaseModel):
    # ... existing fields ...
    quality: str  # 'high' | 'medium' | 'low' | 'unavailable'
    warning: Optional[str] = None
```

**Step 3: Test API**

```bash
curl http://localhost:8000/api/branches/166/forecast?month=2026-03
```

Expected: Response includes `quality` and `warning` fields

**Step 4: Commit**

```bash
git add backend/app/services/forecast_service.py backend/app/schemas.py backend/app/api/forecast.py
git commit -m "feat: integrate forecast quality indicators into API"
```

---

### Task 5.2: Добавить frontend индикатор качества прогноза

**Files:**
- Modify: `frontend/src/components/ForecastChart.tsx`
- Modify: `frontend/src/types/index.ts`

**Step 1: Update TypeScript types**

```typescript
// frontend/src/types/index.ts

export interface BranchForecast {
  // ... existing fields ...
  quality: 'high' | 'medium' | 'low' | 'unavailable';
  warning?: string;
}
```

**Step 2: Add quality indicator to UI**

```tsx
// frontend/src/components/ForecastChart.tsx

const QualityBadge: React.FC<{ quality: string }> = ({ quality }) => {
  const badges = {
    high: { color: 'bg-green-100 text-green-800', label: 'Высокая точность' },
    medium: { color: 'bg-yellow-100 text-yellow-800', label: 'Средняя точность' },
    low: { color: 'bg-red-100 text-red-800', label: 'Низкая точность' },
    unavailable: { color: 'bg-gray-100 text-gray-800', label: 'Недоступно' }
  };

  const badge = badges[quality as keyof typeof badges] || badges.unavailable;

  return (
    <span className={`px-2 py-1 rounded text-xs font-medium ${badge.color}`}>
      {badge.label}
    </span>
  );
};

// In ForecastChart component:
export const ForecastChart: React.FC<Props> = ({ data }) => {
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Прогноз нагрузки</h2>
        <QualityBadge quality={data.quality} />
      </div>

      {data.warning && (
        <div className="mb-4 p-3 bg-yellow-50 border-l-4 border-yellow-400 text-yellow-800 text-sm">
          ⚠️ {data.warning}
        </div>
      )}

      {/* ... existing chart code ... */}
    </div>
  );
};
```

**Step 3: Test in browser**

```bash
cd frontend && npm run dev
```

Navigate to branch 166 forecast page, verify quality badge and warning are displayed.

**Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/components/ForecastChart.tsx
git commit -m "feat: add forecast quality indicator to UI"
```

---

## Testing & Validation

### Run full test suite

```bash
# Backend tests
cd backend
pytest tests/ -v --cov=app

# Frontend type check
cd frontend
npx tsc --noEmit

# Integration test - regenerate forecasts
python3 scripts/generate_forecast.py --month 2026-03

# Validate improvement
python3 scripts/comprehensive_data_analysis.py
```

---

## Documentation

**Updated files:**
- `README.md` - Add note about forecast quality improvements
- `docs/technical_requirements.md` - Update forecast accuracy metrics
- `АНАЛИЗ_ПРОГНОЗОВ.md` - Update with new results

---

## Success Criteria

✅ **Критерии готовности:**
1. [ ] Метаданные филиалов валидированы и синхронизированы
2. [ ] Capacity constraints применяются ко всем прогнозам
3. [ ] Outliers удаляются из обучающих данных
4. [ ] Проблемные филиалы переобучены
5. [ ] Доля филиалов с ошибкой <25% выросла с 33% до ≥60%
6. [ ] Критические филиалы (ID 166, 12) имеют ошибку <100%
7. [ ] API возвращает индикаторы качества прогнозов
8. [ ] UI отображает предупреждения для низкокачественных прогнозов
9. [ ] Все тесты проходят
10. [ ] Документация обновлена

---

**Total estimated time:** 2-3 дня работы (при последовательном выполнении)

**Dependencies:**
- PostgreSQL должен быть запущен
- Модели Prophet уже обучены
- Исторические данные загружены в БД

**Risk mitigation:**
- Все изменения обратимо совместимы (можно откатить postprocessing флагом)
- Валидация на каждом шаге перед переходом к следующему
- Сохранение оригинальных значений перед коррекцией

---

**Plan complete and saved to `docs/plans/2026-02-10-improve-forecast-accuracy.md`**
