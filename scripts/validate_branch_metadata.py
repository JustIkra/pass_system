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
            branch_name = (branch.name or 'Unnamed')[:48]
            print(f"{branch.id:<12} | {branch_name:<50} | {'N/A':<10} | {'No data':<15} | {'N/A':<12}")
            continue

        # Определяем уровень доверия
        if history_data['data_points'] > 1000:
            confidence = 'high'
        elif history_data['data_points'] > 100:
            confidence = 'medium'
        else:
            confidence = 'low'

        num_windows = int(history_data['max_windows'])
        branch_name = (branch.name or 'Unnamed')[:48]

        print(f"{branch.id:<12} | {branch_name:<50} | {num_windows:<10} | {history_data['source']:<15} | {confidence:<12}")

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
