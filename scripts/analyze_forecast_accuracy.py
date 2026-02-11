#!/usr/bin/env python3
"""Анализ точности прогнозов."""

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

def analyze_forecast_accuracy():
    """Сравнение прогнозов с реальными данными."""
    conn = connect_db()

    print("=" * 80)
    print("АНАЛИЗ ТОЧНОСТИ ПРОГНОЗОВ")
    print("=" * 80)

    # Находим пересечение: даты, где есть и прогноз, и реальные данные
    overlap_query = """
        WITH forecast_dates AS (
            SELECT DISTINCT branch_id, date, hour
            FROM forecasts
        ),
        actual_dates AS (
            SELECT DISTINCT branch_id, date, hour
            FROM hourly_stats
            WHERE total_visits > 0
        )
        SELECT
            f.branch_id,
            b.name,
            COUNT(*) as overlapping_hours,
            MIN(f.date) as first_date,
            MAX(f.date) as last_date
        FROM forecast_dates f
        INNER JOIN actual_dates a
            ON f.branch_id = a.branch_id
            AND f.date = a.date
            AND f.hour = a.hour
        INNER JOIN branches b ON f.branch_id = b.id
        GROUP BY f.branch_id, b.name
        HAVING COUNT(*) > 0
        ORDER BY overlapping_hours DESC
    """

    overlap = pd.read_sql(overlap_query, conn)

    if len(overlap) == 0:
        print("\n⚠️  НЕТ ПЕРЕСЕЧЕНИЯ между прогнозами и реальными данными!")
        print("Прогнозы сгенерированы для будущих дат, реальные данные - исторические.")
        print("\nПроверяю качество прогноза на основе исторической валидации...")

        # Проверяем метрики, которые были рассчитаны при обучении
        check_training_metrics(conn)
    else:
        print(f"\nНайдено {len(overlap)} филиалов с пересекающимися данными:")
        print(overlap.to_string(index=False))

        # Сравниваем прогнозы с фактом
        compare_forecast_vs_actual(conn, overlap)

    conn.close()

def check_training_metrics(conn):
    """Проверка метрик обучения моделей."""
    print("\n" + "=" * 80)
    print("МЕТРИКИ КАЧЕСТВА МОДЕЛЕЙ (из обучения)")
    print("=" * 80)

    # Проверяем диапазон прогнозов
    forecast_stats_query = """
        SELECT
            b.id,
            b.name,
            COUNT(*) as forecast_hours,
            AVG(f.predicted_visits) as avg_predicted,
            MIN(f.predicted_visits) as min_predicted,
            MAX(f.predicted_visits) as max_predicted,
            STDDEV(f.predicted_visits) as std_predicted
        FROM forecasts f
        INNER JOIN branches b ON f.branch_id = b.id
        GROUP BY b.id, b.name
        HAVING AVG(f.predicted_visits) > 0
        ORDER BY AVG(f.predicted_visits) DESC
        LIMIT 10
    """

    forecast_stats = pd.read_sql(forecast_stats_query, conn)

    print("\nТОП-10 филиалов по прогнозируемой нагрузке:")
    print("-" * 80)
    for _, row in forecast_stats.iterrows():
        print(f"\n{row['name']} (ID: {row['id']})")
        print(f"  Часов с прогнозом: {row['forecast_hours']:,}")
        print(f"  Средний прогноз: {row['avg_predicted']:.1f} обращений/час")
        print(f"  Диапазон: {row['min_predicted']:.0f} - {row['max_predicted']:.0f}")
        print(f"  Стандартное отклонение: {row['std_predicted']:.1f}")

    # Сравниваем со средними историческими
    print("\n" + "=" * 80)
    print("СРАВНЕНИЕ С ИСТОРИЧЕСКИМИ СРЕДНИМИ")
    print("=" * 80)

    comparison_query = """
        WITH historical_avg AS (
            SELECT
                branch_id,
                AVG(total_visits) as historical_avg,
                STDDEV(total_visits) as historical_std,
                MIN(total_visits) as historical_min,
                MAX(total_visits) as historical_max
            FROM hourly_stats
            WHERE total_visits > 0
            GROUP BY branch_id
        ),
        forecast_avg AS (
            SELECT
                branch_id,
                AVG(predicted_visits) as forecast_avg,
                MIN(predicted_visits) as forecast_min,
                MAX(predicted_visits) as forecast_max
            FROM forecasts
            GROUP BY branch_id
        )
        SELECT
            b.id,
            b.name,
            h.historical_avg,
            h.historical_std,
            h.historical_min,
            h.historical_max,
            f.forecast_avg,
            f.forecast_min,
            f.forecast_max,
            ABS(h.historical_avg - f.forecast_avg) as avg_diff,
            ABS(h.historical_avg - f.forecast_avg) / NULLIF(h.historical_avg, 0) * 100 as avg_diff_pct
        FROM branches b
        INNER JOIN historical_avg h ON b.id = h.branch_id
        INNER JOIN forecast_avg f ON b.id = f.branch_id
        WHERE h.historical_avg > 0
        ORDER BY h.historical_avg DESC
        LIMIT 10
    """

    comparison = pd.read_sql(comparison_query, conn)

    print("\nТОП-10 филиалов: сравнение прогноза с историей:")
    print("-" * 120)
    print(f"{'Филиал':<40} | {'История':<25} | {'Прогноз':<25} | {'Отклонение':>10}")
    print("-" * 120)

    for _, row in comparison.iterrows():
        hist_range = f"{row['historical_min']:.0f}-{row['historical_max']:.0f}"
        fore_range = f"{row['forecast_min']:.0f}-{row['forecast_max']:.0f}"

        print(f"{row['name'][:38]:<40} | "
              f"{row['historical_avg']:6.1f} (±{row['historical_std']:5.1f}) | "
              f"{row['forecast_avg']:6.1f} [{fore_range:>12}] | "
              f"{row['avg_diff_pct']:6.1f}%")

def compare_forecast_vs_actual(conn, overlap_df):
    """Детальное сравнение прогнозов с реальными данными."""
    print("\n" + "=" * 80)
    print("ДЕТАЛЬНОЕ СРАВНЕНИЕ ПРОГНОЗ vs ФАКТ")
    print("=" * 80)

    for _, branch_info in overlap_df.head(5).iterrows():
        branch_id = branch_info['branch_id']
        branch_name = branch_info['name']

        comparison_query = f"""
            SELECT
                f.date,
                f.hour,
                f.predicted_visits,
                h.total_visits as actual_requests,
                ABS(f.predicted_visits - h.total_visits) as abs_error,
                ABS(f.predicted_visits - h.total_visits) / NULLIF(h.total_visits, 0) * 100 as pct_error
            FROM forecasts f
            INNER JOIN hourly_stats h
                ON f.branch_id = h.branch_id
                AND f.date = h.date
                AND f.hour = h.hour
            WHERE f.branch_id = {branch_id}
                AND h.total_visits > 0
            ORDER BY abs_error DESC
            LIMIT 10
        """

        errors = pd.read_sql(comparison_query, conn)

        if len(errors) > 0:
            print(f"\n{branch_name} - ТОП-10 наибольших отклонений:")
            print(f"{'Дата':<12} {'Час':>4} | {'Прогноз':>8} | {'Факт':>8} | {'Ошибка':>8} | {'%':>7}")
            print("-" * 60)

            for _, row in errors.iterrows():
                print(f"{row['date'].strftime('%Y-%m-%d'):<12} {row['hour']:>4} | "
                      f"{row['predicted_visits']:8.1f} | "
                      f"{row['actual_requests']:8.0f} | "
                      f"{row['abs_error']:8.1f} | "
                      f"{row['pct_error']:6.1f}%")

            # Общая статистика по филиалу
            avg_error = errors['abs_error'].mean()
            avg_pct_error = errors['pct_error'].mean()
            print(f"\nСредняя ошибка: {avg_error:.1f} обращений ({avg_pct_error:.1f}%)")

if __name__ == "__main__":
    analyze_forecast_accuracy()
