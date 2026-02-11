#!/usr/bin/env python3
"""Быстрая проверка статуса улучшений Phase 2-4.

Этот скрипт:
1. Проверяет наличие критических компонентов
2. Анализирует текущие прогнозы для проблемных филиалов
3. Сравнивает с baseline метриками
4. Показывает что нужно сделать дальше
"""

import sys
from pathlib import Path

# Add backend to path
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker
import os

# Database connection
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://mfc_user:mfc_pass@localhost:5432/mfc_db"
)


def check_components():
    """Проверяет наличие всех компонентов улучшений."""
    print("=" * 80)
    print("ПРОВЕРКА КОМПОНЕНТОВ PHASE 2-4")
    print("=" * 80)

    components = {
        "Phase 2: Постобработка": [
            (_BACKEND_DIR / "app" / "ml" / "postprocessing.py", "Модуль постобработки"),
            (_BACKEND_DIR / "app" / "ml" / "prediction.py", "Интеграция в prediction.py"),
        ],
        "Phase 3: Очистка данных": [
            (_BACKEND_DIR / "app" / "ml" / "training.py", "Outlier detection в training.py"),
            (_SCRIPT_DIR / "retrain_problematic_branches.py", "Скрипт переобучения"),
        ],
        "Phase 1: Метаданные": [
            (_BACKEND_DIR / "app" / "services" / "branch_metadata.py", "Валидатор метаданных"),
            (_SCRIPT_DIR / "validate_branch_metadata.py", "Скрипт валидации"),
        ],
    }

    all_ok = True
    for phase, files in components.items():
        print(f"\n{phase}:")
        for file_path, description in files:
            exists = file_path.exists()
            status = "✅" if exists else "❌"
            print(f"  {status} {description}: {file_path.name}")
            if not exists:
                all_ok = False

    return all_ok


def check_database_metadata():
    """Проверяет наличие таблицы branch_metadata и данных."""
    print("\n" + "=" * 80)
    print("ПРОВЕРКА МЕТАДАННЫХ ФИЛИАЛОВ")
    print("=" * 80)

    try:
        connect_args = {}
        if "sqlite" in DATABASE_URL:
            connect_args = {"check_same_thread": False}

        engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Проверяем существование таблицы
        result = session.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'branch_metadata'"
        ))
        table_exists = result.scalar() > 0

        if not table_exists:
            # Try SQLite syntax
            result = session.execute(text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name='branch_metadata'"
            ))
            table_exists = result.scalar() > 0

        if table_exists:
            # Считаем записи
            result = session.execute(text("SELECT COUNT(*) FROM branch_metadata"))
            count = result.scalar()
            print(f"✅ Таблица branch_metadata существует: {count} записей")

            # Проверяем проблемные филиалы
            problematic = [12, 166]
            for bid in problematic:
                result = session.execute(
                    text("SELECT num_windows, max_capacity FROM branch_metadata WHERE branch_id = :bid"),
                    {"bid": bid}
                ).fetchone()
                if result:
                    print(f"  ✅ Филиал {bid}: {result[0]} окон, capacity = {result[1]}")
                else:
                    print(f"  ❌ Филиал {bid}: метаданные отсутствуют")
        else:
            print("❌ Таблица branch_metadata НЕ существует")
            print("   Запустите: python3 scripts/validate_branch_metadata.py")

        session.close()
        return table_exists

    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        print(f"   DATABASE_URL: {DATABASE_URL}")
        return False


def check_forecast_data():
    """Проверяет прогнозы для проблемных филиалов."""
    print("\n" + "=" * 80)
    print("ПРОВЕРКА ПРОГНОЗОВ")
    print("=" * 80)

    try:
        connect_args = {}
        if "sqlite" in DATABASE_URL:
            connect_args = {"check_same_thread": False}

        engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Проблемные филиалы
        problematic = {
            12: {"name": "МФЦ №1", "baseline_mape": 288},
            166: {"name": "Суджанский район", "baseline_mape": 1665},
        }

        print("\nПроблемные филиалы (baseline):")
        for bid, info in problematic.items():
            print(f"  Филиал {bid} ({info['name']}): wMAPE = {info['baseline_mape']}%")

        print("\nТекущие прогнозы:")
        has_forecasts = False

        for bid, info in problematic.items():
            # Проверяем существование прогнозов
            result = session.execute(
                text("SELECT COUNT(*) FROM forecasts WHERE branch_id = :bid"),
                {"bid": bid}
            ).scalar()

            if result > 0:
                has_forecasts = True
                # Максимальное значение прогноза
                max_pred = session.execute(
                    text("SELECT MAX(predicted_visits) FROM forecasts WHERE branch_id = :bid"),
                    {"bid": bid}
                ).scalar()

                # Средний прогноз
                avg_pred = session.execute(
                    text("SELECT AVG(predicted_visits) FROM forecasts WHERE branch_id = :bid"),
                    {"bid": bid}
                ).scalar()

                # Capacity из метаданных
                capacity_result = session.execute(
                    text("SELECT max_capacity FROM branch_metadata WHERE branch_id = :bid"),
                    {"bid": bid}
                ).scalar()

                capacity = capacity_result if capacity_result else "N/A"

                # Проверка на превышение capacity
                if capacity != "N/A" and max_pred > capacity:
                    status = "❌ ПРЕВЫШАЕТ CAPACITY"
                elif capacity != "N/A" and max_pred <= capacity:
                    status = "✅ В пределах capacity"
                else:
                    status = "⚠️  Capacity не определен"

                print(f"\n  Филиал {bid} ({info['name']}):")
                print(f"    Прогнозов: {result}")
                print(f"    Max прогноз: {max_pred:.1f} (capacity: {capacity})")
                print(f"    Avg прогноз: {avg_pred:.1f}")
                print(f"    Статус: {status}")

                if status.startswith("❌"):
                    print(f"    ⚠️  ТРЕБУЕТСЯ РЕГЕНЕРАЦИЯ с постобработкой!")
            else:
                print(f"\n  Филиал {bid} ({info['name']}): ❌ Прогнозы отсутствуют")

        if not has_forecasts:
            print("\n⚠️  Прогнозы не найдены. Запустите:")
            print("   python3 scripts/generate_forecast.py --month 2026-03")

        session.close()
        return has_forecasts

    except Exception as e:
        print(f"❌ Ошибка при проверке прогнозов: {e}")
        return False


def check_models():
    """Проверяет наличие обученных моделей."""
    print("\n" + "=" * 80)
    print("ПРОВЕРКА МОДЕЛЕЙ")
    print("=" * 80)

    models_dir = _SCRIPT_DIR.parent / "models"

    if not models_dir.exists():
        print("❌ Директория models/ не существует")
        return False

    # Проверяем модели для проблемных филиалов
    problematic = [12, 166]
    all_exist = True

    for bid in problematic:
        visits_model = models_dir / f"branch_{bid}_visits.pkl"
        wait_model = models_dir / f"branch_{bid}_wait.pkl"

        visits_ok = visits_model.exists()
        wait_ok = wait_model.exists()

        status = "✅" if (visits_ok and wait_ok) else "❌"
        print(f"  {status} Филиал {bid}: visits={visits_ok}, wait={wait_ok}")

        if not (visits_ok and wait_ok):
            all_exist = False

    if not all_exist:
        print("\n⚠️  Некоторые модели отсутствуют. Запустите:")
        print("   python3 scripts/retrain_problematic_branches.py --branch-ids 12,166")

    return all_exist


def check_integration():
    """Проверяет интеграцию постобработки в код."""
    print("\n" + "=" * 80)
    print("ПРОВЕРКА ИНТЕГРАЦИИ")
    print("=" * 80)

    prediction_file = _BACKEND_DIR / "app" / "ml" / "prediction.py"

    if not prediction_file.exists():
        print("❌ prediction.py не найден")
        return False

    content = prediction_file.read_text()

    checks = {
        "Import постобработки": "from app.ml.postprocessing import postprocess_forecast",
        "Параметр apply_postprocessing": "apply_postprocessing: bool = True",
        "Вызов postprocess_forecast": "postprocess_forecast(",
    }

    all_ok = True
    for check_name, pattern in checks.items():
        found = pattern in content
        status = "✅" if found else "❌"
        print(f"  {status} {check_name}")
        if not found:
            all_ok = False

    return all_ok


def print_next_steps():
    """Выводит следующие шаги."""
    print("\n" + "=" * 80)
    print("СЛЕДУЮЩИЕ ШАГИ")
    print("=" * 80)

    print("\n1. Если метаданные отсутствуют:")
    print("   python3 scripts/validate_branch_metadata.py")

    print("\n2. Если модели устарели или отсутствуют:")
    print("   python3 scripts/retrain_problematic_branches.py --branch-ids 12,166 --workers 4")

    print("\n3. Если прогнозы устарели или превышают capacity:")
    print("   python3 scripts/generate_forecast.py --month 2026-03 --workers 8")

    print("\n4. Запустить комплексный анализ:")
    print("   python3 scripts/comprehensive_data_analysis.py > docs/IMPROVEMENT_REPORT.md")

    print("\n5. Запустить тесты:")
    print("   pytest tests/test_critical_improvements.py -v")

    print("\n6. Создать итоговый отчет:")
    print("   Заполните docs/IMPROVEMENT_SUMMARY.md на основе результатов")


def main():
    """Основная функция проверки."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "ПРОВЕРКА СТАТУСА PHASE 2-4" + " " * 32 + "║")
    print("╚" + "=" * 78 + "╝")

    # Проверяем компоненты
    components_ok = check_components()

    # Проверяем интеграцию
    integration_ok = check_integration()

    # Проверяем БД метаданные
    metadata_ok = check_database_metadata()

    # Проверяем модели
    models_ok = check_models()

    # Проверяем прогнозы
    forecasts_ok = check_forecast_data()

    # Итоги
    print("\n" + "=" * 80)
    print("ИТОГОВЫЙ СТАТУС")
    print("=" * 80)

    status = {
        "Компоненты кода": components_ok,
        "Интеграция постобработки": integration_ok,
        "Метаданные филиалов": metadata_ok,
        "Обученные модели": models_ok,
        "Прогнозы в БД": forecasts_ok,
    }

    for check_name, is_ok in status.items():
        symbol = "✅" if is_ok else "❌"
        print(f"{symbol} {check_name}")

    all_ok = all(status.values())

    if all_ok:
        print("\n" + "🎉" * 40)
        print("ВСЕ КОМПОНЕНТЫ ГОТОВЫ!")
        print("Можно запускать валидацию (см. docs/PHASE_4_VALIDATION_INSTRUCTIONS.md)")
        print("🎉" * 40)
    else:
        print("\n⚠️  Есть проблемы. См. следующие шаги:")
        print_next_steps()

    print("\n")


if __name__ == "__main__":
    main()
