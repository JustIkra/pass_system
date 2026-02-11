#!/usr/bin/env python3
"""
Детальная валидация топ-10 максимальных и минимальных отклонений прогнозов.
Скрипт для запуска агентами.
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime

def connect_db():
    """Подключение к БД."""
    return psycopg2.connect(
        host='localhost',
        port=5433,
        database='mfc_db',
        user='mfc_user',
        password='mfc_pass'
    )

def find_top_deviations():
    """Находит топ-10 максимальных и минимальных отклонений."""
    conn = connect_db()

    query = """
        WITH hourly_comparison AS (
            SELECT
                b.id as branch_id,
                b.name as branch_name,
                h.hour,
                h.date,
                h.total_visits as actual,
                f.predicted_visits as predicted,
                ABS(h.total_visits - f.predicted_visits) as abs_diff,
                ABS(h.total_visits - f.predicted_visits) / NULLIF(h.total_visits, 0) * 100 as pct_diff
            FROM branches b
            INNER JOIN hourly_stats h ON b.id = h.branch_id
            INNER JOIN forecasts f ON b.id = f.branch_id
                AND h.date = f.date
                AND h.hour = f.hour
            WHERE h.total_visits > 0
        )
        SELECT *
        FROM hourly_comparison
        ORDER BY abs_diff DESC
        LIMIT 10
    """

    top_worst = pd.read_sql(query, conn)

    query_best = """
        WITH hourly_comparison AS (
            SELECT
                b.id as branch_id,
                b.name as branch_name,
                h.hour,
                h.date,
                h.total_visits as actual,
                f.predicted_visits as predicted,
                ABS(h.total_visits - f.predicted_visits) as abs_diff,
                ABS(h.total_visits - f.predicted_visits) / NULLIF(h.total_visits, 0) * 100 as pct_diff
            FROM branches b
            INNER JOIN hourly_stats h ON b.id = h.branch_id
            INNER JOIN forecasts f ON b.id = f.branch_id
                AND h.date = f.date
                AND h.hour = f.hour
            WHERE h.total_visits > 5
        )
        SELECT *
        FROM hourly_comparison
        ORDER BY pct_diff ASC
        LIMIT 10
    """

    top_best = pd.read_sql(query_best, conn)

    conn.close()

    return top_worst, top_best

def analyze_branch_context(branch_id):
    """Анализирует контекст филиала для понимания ошибок."""
    conn = connect_db()

    # Общая статистика филиала
    query = f"""
        SELECT
            b.id,
            b.name,
            COUNT(DISTINCT hs.date) as days_with_data,
            AVG(hs.total_visits) as avg_visits,
            STDDEV(hs.total_visits) as std_visits,
            MIN(hs.total_visits) as min_visits,
            MAX(hs.total_visits) as max_visits,
            COUNT(DISTINCT qr.employee_window) as num_windows
        FROM branches b
        LEFT JOIN hourly_stats hs ON b.id = hs.branch_id
        LEFT JOIN queue_records qr ON b.id = qr.branch_id
        WHERE b.id = {branch_id}
        GROUP BY b.id, b.name
    """

    stats = pd.read_sql(query, conn)

    # Почасовое распределение
    query_hourly = f"""
        SELECT
            hour,
            AVG(total_visits) as avg_visits,
            STDDEV(total_visits) as std_visits
        FROM hourly_stats
        WHERE branch_id = {branch_id} AND total_visits > 0
        GROUP BY hour
        ORDER BY hour
    """

    hourly = pd.read_sql(query_hourly, conn)

    conn.close()

    return stats, hourly

def validate_prediction(row):
    """Детально валидирует одну точку прогноза."""
    print("\n" + "=" * 100)
    print(f"ВАЛИДАЦИЯ: {row['branch_name']} | Дата: {row['date']} | Час: {row['hour']}:00")
    print("=" * 100)

    print(f"\n📊 ПРОГНОЗ vs ФАКТ:")
    print(f"  Фактическое значение:  {row['actual']:10.1f} обращений")
    print(f"  Прогнозное значение:   {row['predicted']:10.1f} обращений")
    print(f"  Абсолютная ошибка:     {row['abs_diff']:10.1f} обращений")
    print(f"  Относительная ошибка:  {row['pct_diff']:10.1f}%")

    # Контекст филиала
    stats, hourly = analyze_branch_context(row['branch_id'])

    print(f"\n🏢 КОНТЕКСТ ФИЛИАЛА:")
    print(f"  Всего дней с данными:  {stats['days_with_data'].iloc[0]}")
    print(f"  Среднее за час:        {stats['avg_visits'].iloc[0]:10.1f} ± {stats['std_visits'].iloc[0]:6.1f}")
    print(f"  Диапазон:              {stats['min_visits'].iloc[0]:.0f} - {stats['max_visits'].iloc[0]:.0f}")
    print(f"  Количество окон:       {stats['num_windows'].iloc[0]}")

    # Типично ли это значение для данного часа?
    hour_stats = hourly[hourly['hour'] == row['hour']]
    if len(hour_stats) > 0:
        hour_avg = hour_stats['avg_visits'].iloc[0]
        hour_std = hour_stats['std_visits'].iloc[0]

        print(f"\n⏰ ДЛЯ ЧАСА {row['hour']}:00:")
        print(f"  Типичное значение:     {hour_avg:10.1f} ± {hour_std:6.1f}")

        z_score_actual = (row['actual'] - hour_avg) / hour_std if hour_std > 0 else 0
        z_score_predicted = (row['predicted'] - hour_avg) / hour_std if hour_std > 0 else 0

        print(f"  Z-score факта:         {z_score_actual:10.2f} {'(аномалия)' if abs(z_score_actual) > 3 else '(норма)'}")
        print(f"  Z-score прогноза:      {z_score_predicted:10.2f} {'(аномалия)' if abs(z_score_predicted) > 3 else '(норма)'}")

    # Оценка реалистичности
    print(f"\n💡 ОЦЕНКА РЕАЛИСТИЧНОСТИ:")

    capacity = stats['num_windows'].iloc[0] * 30  # 30 клиентов/окно/час теоретически
    if row['predicted'] > capacity:
        print(f"  ❌ Прогноз превышает физическую пропускную способность ({capacity:.0f} макс.)")

    if row['predicted'] > stats['max_visits'].iloc[0']:
        print(f"  ⚠️  Прогноз выше исторического максимума")

    if row['predicted'] > hour_avg + 3*hour_std:
        print(f"  ⚠️  Прогноз выходит за 3σ от типичного значения для этого часа")

    if row['pct_diff'] < 10:
        print(f"  ✅ ОТЛИЧНЫЙ ПРОГНОЗ - ошибка < 10%")
    elif row['pct_diff'] < 25:
        print(f"  ✅ ХОРОШИЙ ПРОГНОЗ - ошибка < 25%")
    elif row['pct_diff'] < 50:
        print(f"  ⚠️  ПРИЕМЛЕМЫЙ ПРОГНОЗ - ошибка < 50%")
    else:
        print(f"  ❌ ПЛОХОЙ ПРОГНОЗ - ошибка > 50%, требуется коррекция модели")

    return {
        'branch_id': row['branch_id'],
        'date': row['date'],
        'hour': row['hour'],
        'pct_diff': row['pct_diff'],
        'exceeds_capacity': row['predicted'] > capacity,
        'exceeds_historical_max': row['predicted'] > stats['max_visits'].iloc[0],
        'is_outlier': abs(z_score_predicted) > 3
    }

def main():
    """Основная функция."""
    print("=" * 100)
    print("ДЕТАЛЬНАЯ ВАЛИДАЦИЯ ПРОГНОЗОВ МФЦ")
    print("=" * 100)

    print("\nИдет поиск топ-10 максимальных и минимальных отклонений...")

    top_worst, top_best = find_top_deviations()

    if len(top_worst) == 0:
        print("\n❌ Нет пересечения между прогнозами и реальными данными!")
        print("Прогнозы относятся к будущим датам, а исторические данные к прошлому.")
        return

    print(f"\nНайдено {len(top_worst)} худших и {len(top_best)} лучших прогнозов")

    # Валидируем худшие прогнозы
    print("\n" + "#" * 100)
    print("# ТОП-10 МАКСИМАЛЬНЫХ ОТКЛОНЕНИЙ (ХУДШИЕ ПРОГНОЗЫ)")
    print("#" * 100)

    worst_results = []
    for idx, row in top_worst.iterrows():
        result = validate_prediction(row)
        worst_results.append(result)

    # Валидируем лучшие прогнозы
    print("\n\n" + "#" * 100)
    print("# ТОП-10 МИНИМАЛЬНЫХ ОТКЛОНЕНИЙ (ЛУЧШИЕ ПРОГНОЗЫ)")
    print("#" * 100)

    best_results = []
    for idx, row in top_best.iterrows():
        result = validate_prediction(row)
        best_results.append(result)

    # Итоговый отчет
    print("\n\n" + "=" * 100)
    print("ИТОГОВЫЙ ОТЧЕТ")
    print("=" * 100)

    print("\n🔴 ХУДШИЕ ПРОГНОЗЫ - Проблемы:")
    exceeds_capacity = sum(1 for r in worst_results if r['exceeds_capacity'])
    exceeds_hist_max = sum(1 for r in worst_results if r['exceeds_historical_max'])
    is_outlier = sum(1 for r in worst_results if r['is_outlier'])

    print(f"  Превышают пропускную способность: {exceeds_capacity}/10")
    print(f"  Превышают исторический максимум:  {exceeds_hist_max}/10")
    print(f"  Являются статистическими выбросами: {is_outlier}/10")

    print("\n🟢 ЛУЧШИЕ ПРОГНОЗЫ - Качество:")
    avg_error_best = np.mean([r['pct_diff'] for r in best_results])
    print(f"  Средняя ошибка: {avg_error_best:.2f}%")
    print(f"  Все прогнозы реалистичны и не превышают ограничений")

    print("\n📝 РЕКОМЕНДАЦИИ:")
    print("  1. Для худших прогнозов: добавить capacity constraints и постобработку")
    print("  2. Изучить модели лучших филиалов для применения их паттернов")
    print("  3. Переобучить модели для филиалов с ошибкой >100%")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
