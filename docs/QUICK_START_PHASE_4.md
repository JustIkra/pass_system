# Phase 4: Quick Start Guide

> **TL;DR:** Код Phase 2-4 уже написан. Нужно только запустить скрипты и собрать метрики.

---

## Статус: 90% готово ✅

- ✅ Phase 1 (Metadata): Завершено
- ✅ Phase 2 (Postprocessing): Код написан и интегрирован
- ✅ Phase 3 (Outlier cleaning): Реализовано
- ❌ Phase 4 (Validation): **Требуется запуск скриптов**

---

## Запуск Phase 4 (5 команд)

### Шаг 1: Проверка статуса

```bash
python3 scripts/check_improvements_status.py
```

**Что проверяет:**
- Все компоненты на месте
- Метаданные филиалов заполнены
- Модели существуют
- Прогнозы в БД

### Шаг 2: Переобучение проблемных филиалов

```bash
python3 scripts/retrain_problematic_branches.py --branch-ids 12,166 --workers 4
```

**Что делает:**
- Загружает данные для филиалов 12 и 166
- Удаляет outliers (Z-score > 3σ)
- Обучает новые Prophet модели
- Сохраняет в `models/branch_12_*.pkl` и `models/branch_166_*.pkl`

**Ожидаемое время:** 5-10 минут

### Шаг 3: Регенерация прогнозов

```bash
python3 scripts/generate_forecast.py --month 2026-03 --workers 8
```

**Что делает:**
- Генерирует прогнозы для всех филиалов на март 2026
- Применяет постобработку (`apply_postprocessing=True`)
- Ограничивает по capacity constraints
- Сохраняет в таблицу `forecasts`

**Ожидаемое время:** 10-15 минут

### Шаг 4: Анализ метрик

```bash
python3 scripts/comprehensive_data_analysis.py > docs/IMPROVEMENT_REPORT.md
```

**Что делает:**
- Вычисляет wMAPE для всех филиалов
- Сравнивает прогнозы с историей
- Генерирует детальный отчет

**Ожидаемое время:** 3-5 минут

### Шаг 5: Запуск тестов

```bash
cd backend && pytest tests/test_critical_improvements.py -v
```

**Что проверяет:**
- Прогнозы не превышают capacity
- Outlier cleaning работает
- Постобработка применяется
- Метрики улучшились

**Ожидаемый результат:** Все тесты PASSED (GREEN)

---

## Критерии успеха

Откройте `docs/IMPROVEMENT_REPORT.md` и проверьте:

| Метрика | Baseline | Target | Статус |
|---------|----------|--------|--------|
| Филиалов с wMAPE < 25% | 33% | ≥60% | ⏳ |
| Филиал 166 (Суджанский) | 1665% | <100% | ⏳ |
| Филиал 12 (МФЦ №1) | 288% | <100% | ⏳ |
| Средний wMAPE | ~55% | <30% | ⏳ |

Если все критерии выполнены - **Phase 4 завершена** ✅

---

## Что делать если тесты упали

### Тест: `test_capacity_constraint_all_branches`

**Симптом:** Прогнозы превышают capacity

**Решение:**
```bash
# Проверить метаданные
python3 -c "
from backend.app.database import SessionLocal
from backend.app.models import BranchMetadata
db = SessionLocal()
m = db.query(BranchMetadata).filter_by(branch_id=166).first()
print(f'Capacity: {m.max_capacity if m else "Missing"}')
db.close()
"

# Если метаданных нет - запустить валидацию
python3 scripts/validate_branch_metadata.py
```

### Тест: `test_outlier_cleaning_does_not_remove_too_much`

**Симптом:** Удаляется >10% данных

**Решение:** Ослабить порог outlier detection

```python
# backend/app/ml/training.py, строка 189
# Изменить threshold с 3.0 на 4.0
df = detect_and_remove_outliers(df, y_col="y", threshold=4.0)
```

### Тест: `test_end_to_end_branch_166_forecast_correction`

**Симптом:** wMAPE не улучшился

**Решение:**
```bash
# 1. Проверить что постобработка применяется
grep -n "apply_postprocessing" backend/app/ml/prediction.py

# 2. Проверить логи регенерации
python3 scripts/generate_forecast.py --branch-id 166 --month 2026-03 --log-level DEBUG

# 3. Проверить что модель переобучена
ls -lh models/branch_166_*.pkl
```

---

## После завершения Phase 4

### 1. Создать итоговый отчет

Заполните `docs/IMPROVEMENT_SUMMARY.md`:

```markdown
## Метрики ПОСЛЕ

- Филиалов с wMAPE < 25%: __% (__ из 44)
- Филиал 166: wMAPE = __%
- Филиал 12: wMAPE = __%
- Средний wMAPE: __%
```

### 2. Коммит результатов

```bash
git add models/branch_*.pkl
git add docs/IMPROVEMENT_REPORT.md docs/IMPROVEMENT_SUMMARY.md
git commit -m "docs: Phase 4 validation complete - forecasts improved"
```

### 3. Передать задачу Frontend Developer

**Task для Frontend:** Добавить UI индикаторы
- Capacity utilization gauge на Branch Detail странице
- Warning если прогноз >80% capacity
- Tooltip с количеством окон филиала

---

## Полезные ссылки

- **Детальные инструкции:** `docs/PHASE_4_VALIDATION_INSTRUCTIONS.md`
- **Статус реализации:** `docs/PHASE_2-4_IMPLEMENTATION_STATUS.md`
- **План Phase 1-5:** `docs/plans/2026-02-10-improve-forecast-accuracy.md`
- **Тесты:** `tests/test_critical_improvements.py`

---

## Вопросы?

**Q: Сколько времени займет Phase 4?**

A: 20-30 минут (если все работает без ошибок)

**Q: Нужно ли переобучать все 44 филиала?**

A: Нет, достаточно проблемных (12 и 166). Остальные работают приемлемо.

**Q: Можно ли запустить шаги 2-3 параллельно?**

A: Нет, нужна последовательность:
1. Сначала переобучить модели (шаг 2)
2. Потом сгенерировать прогнозы с новыми моделями (шаг 3)

**Q: Что если базы данных нет?**

A: Запустите ETL pipeline:
```bash
python3 scripts/init_db.py --data-dir "./Исходные данные АИС"
python3 scripts/validate_branch_metadata.py
```
