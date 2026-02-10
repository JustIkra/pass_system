"""Постобработка прогнозов для повышения реалистичности."""

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from app.models import Branch, HourlyStat, BranchMetadata


def get_branch_capacity(db: Session, branch_id: int) -> float:
    """
    Вычисляет максимальную пропускную способность филиала.

    Приоритет источников данных:
    1. Валидированные метаданные из branch_metadata (наивысший приоритет)
    2. Максимум из hourly_stats.num_windows_active
    3. Оценка по максимуму посещений в истории

    Args:
        db: Сессия БД
        branch_id: ID филиала

    Returns:
        Максимальное кол-во обращений/час
    """
    from sqlalchemy import func

    # Приоритет 1: Валидированные метаданные из Phase 1
    metadata = db.query(BranchMetadata).filter(
        BranchMetadata.branch_id == branch_id
    ).first()

    if metadata and metadata.max_capacity:
        return float(metadata.max_capacity)

    # Приоритет 2: Максимум из исторических данных hourly_stats
    num_windows = db.query(func.max(HourlyStat.num_windows_active))\
        .filter(HourlyStat.branch_id == branch_id)\
        .filter(HourlyStat.num_windows_active > 0)\
        .scalar()

    if num_windows:
        # Консервативная оценка: 25 клиентов/окно/час
        # (реально меньше, т.к. есть время на обслуживание ~13 мин/клиент)
        return float(num_windows * 25)

    # Приоритет 3 (fallback): Оценка по максимуму посещений в истории
    max_visits = db.query(func.max(HourlyStat.total_visits))\
        .filter(HourlyStat.branch_id == branch_id)\
        .scalar()

    return max_visits * 1.2 if max_visits else 100.0  # +20% запас или дефолт


def get_historical_bounds(db: Session, branch_id: int, confidence: float = 3.0) -> tuple:
    """
    Вычисляет разумные границы на основе истории (mean ± N*std).

    Args:
        db: Сессия БД
        branch_id: ID филиала
        confidence: Количество стандартных отклонений (3.0 = 99.7% данных)

    Returns:
        (lower_bound, upper_bound)
    """
    # SQLite doesn't support stddev, so we compute it manually
    visits = db.query(HourlyStat.total_visits).filter(
        HourlyStat.branch_id == branch_id,
        HourlyStat.total_visits > 0
    ).all()

    if not visits:
        return (0, 100)

    values = np.array([v[0] for v in visits])
    mean = np.mean(values)
    std = np.std(values) if len(values) > 1 else mean * 0.5

    lower = max(0, mean - confidence * std)
    upper = mean + confidence * std

    return (lower, upper)


def get_hourly_bounds(db: Session, branch_id: int, hour: int) -> tuple:
    """
    Вычисляет границы для конкретного часа (учитывает почасовые паттерны).

    Args:
        db: Сессия БД
        branch_id: ID филиала
        hour: Час дня (0-23)

    Returns:
        (lower_bound, upper_bound)
    """
    # SQLite doesn't support stddev, so we compute it manually
    visits = db.query(HourlyStat.total_visits).filter(
        HourlyStat.branch_id == branch_id,
        HourlyStat.hour == hour,
        HourlyStat.total_visits > 0
    ).all()

    if not visits:
        return get_historical_bounds(db, branch_id)

    values = np.array([v[0] for v in visits])
    mean = np.mean(values)
    std = np.std(values) if len(values) > 1 else mean * 0.5

    # Для почасовых паттернов используем более строгие границы (2.5σ)
    lower = max(0, mean - 2.5 * std)
    upper = mean + 2.5 * std

    return (lower, upper)


def apply_constraints(
    predictions: np.ndarray,
    branch_id: int,
    hours: np.ndarray,
    db: Session,
    use_hourly: bool = True
) -> np.ndarray:
    """
    Применяет ограничения к прогнозам.

    Args:
        predictions: Массив прогнозных значений
        branch_id: ID филиала
        hours: Массив часов, соответствующих прогнозам
        db: Сессия БД
        use_hourly: Использовать почасовые границы (более точно, но медленнее)

    Returns:
        Скорректированный массив прогнозов
    """
    # 1. Capacity constraint (жесткое ограничение)
    capacity = get_branch_capacity(db, branch_id)
    predictions = np.minimum(predictions, capacity)

    # 2. Statistical bounds (мягкое ограничение)
    if use_hourly and len(hours) > 0:
        # Применяем почасовые границы
        corrected = []
        for pred, hour in zip(predictions, hours):
            lower, upper = get_hourly_bounds(db, branch_id, int(hour))
            corrected.append(np.clip(pred, lower, upper))
        predictions = np.array(corrected)
    else:
        # Применяем общие границы
        lower, upper = get_historical_bounds(db, branch_id)
        predictions = np.clip(predictions, lower, upper)

    return predictions


def smooth_predictions(predictions: np.ndarray, window: int = 3) -> np.ndarray:
    """
    Сглаживает прогнозы скользящим средним для устранения резких скачков.

    Args:
        predictions: Массив прогнозов
        window: Размер окна сглаживания

    Returns:
        Сглаженный массив
    """
    if len(predictions) < window:
        return predictions

    # Скользящее среднее
    smoothed = np.convolve(predictions, np.ones(window)/window, mode='same')

    # Восстанавливаем края (они искажаются при свертке)
    smoothed[:window//2] = predictions[:window//2]
    smoothed[-(window//2):] = predictions[-(window//2):]

    return smoothed


def detect_outliers_in_predictions(
    predictions: np.ndarray,
    threshold: float = 3.0
) -> np.ndarray:
    """
    Находит выбросы в прогнозах (аномально высокие/низкие значения).

    Args:
        predictions: Массив прогнозов
        threshold: Z-score порог для определения выброса

    Returns:
        Булев массив (True = выброс)
    """
    if len(predictions) < 3:
        return np.zeros(len(predictions), dtype=bool)

    mean = np.mean(predictions)
    std = np.std(predictions)

    if std == 0:
        return np.zeros(len(predictions), dtype=bool)

    z_scores = np.abs((predictions - mean) / std)
    return z_scores > threshold


def postprocess_forecast(
    predictions: pd.DataFrame,
    branch_id: int,
    db: Session,
    apply_smoothing: bool = True,
    correct_outliers: bool = True
) -> pd.DataFrame:
    """
    Полная постобработка прогнозов.

    Args:
        predictions: DataFrame с колонками ['date', 'hour', 'predicted_visits', ...]
        branch_id: ID филиала
        db: Сессия БД
        apply_smoothing: Применять сглаживание
        correct_outliers: Корректировать выбросы

    Returns:
        DataFrame со скорректированными прогнозами
    """
    if len(predictions) == 0:
        return predictions

    # Сохраняем оригинальные значения
    predictions['predicted_visits_original'] = predictions['predicted_visits'].copy()

    values = predictions['predicted_visits'].values
    hours = predictions['hour'].values

    # 1. Применяем ограничения
    values = apply_constraints(values, branch_id, hours, db, use_hourly=True)

    # 2. Детектируем и корректируем выбросы
    if correct_outliers:
        outliers = detect_outliers_in_predictions(values)
        if outliers.any():
            # Заменяем выбросы интерполяцией соседних значений
            for idx in np.where(outliers)[0]:
                left = values[max(0, idx-2):idx]
                right = values[idx+1:min(len(values), idx+3)]
                neighbors = np.concatenate([left, right])
                if len(neighbors) > 0:
                    values[idx] = np.median(neighbors)

    # 3. Сглаживание
    if apply_smoothing:
        values = smooth_predictions(values, window=3)

    # 4. Финальное ограничение (на случай если сглаживание вышло за границы)
    capacity = get_branch_capacity(db, branch_id)
    values = np.clip(values, 0, capacity)

    predictions['predicted_visits'] = values

    # Вычисляем насколько изменился прогноз
    predictions['correction_pct'] = (
        (predictions['predicted_visits'] - predictions['predicted_visits_original']) /
        predictions['predicted_visits_original'] * 100
    )

    return predictions


# Пример использования
if __name__ == "__main__":
    from app.database import SessionLocal

    db = SessionLocal()

    # Тестируем на проблемном филиале (Суджанский район)
    branch_id = 166

    print(f"Capacity для филиала {branch_id}: {get_branch_capacity(db, branch_id):.0f}")
    print(f"Historical bounds: {get_historical_bounds(db, branch_id)}")
    print(f"Hourly bounds (10:00): {get_hourly_bounds(db, branch_id, 10)}")

    db.close()
