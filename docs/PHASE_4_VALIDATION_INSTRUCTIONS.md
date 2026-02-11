# Phase 4: Инструкции по валидации улучшений

## Статус реализации

✅ **Phase 1 (Metadata):** Завершено
✅ **Phase 2 (Postprocessing):** Завершено
✅ **Phase 3 (Outlier cleaning):** Завершено
❌ **Phase 4 (Validation):** Требуется выполнение

## Что уже реализовано

### Phase 2: Постобработка прогнозов
- ✅ `backend/app/ml/postprocessing.py` - полностью реализован
  - `get_branch_capacity()` - использует валидированные метаданные из `branch_metadata`
  - `apply_constraints()` - ограничивает прогнозы по capacity
  - `smooth_predictions()` - сглаживание скользящим средним
  - `postprocess_forecast()` - полный цикл постобработки

- ✅ `backend/app/ml/prediction.py` - интеграция выполнена
  - Импорт `postprocess_forecast` (строка 38)
  - Применение в `generate_forecast()` (строки 272-288)
  - Применение в `generate_forecast_range()` (строки 410-426)
  - Параметр `apply_postprocessing=True` по умолчанию

- ✅ `scripts/generate_forecast.py` - использует постобработку
  - Все вызовы используют `apply_postprocessing=True` (строки 82, 114, 335, 340)

### Phase 3: Очистка обучающих данных
- ✅ `backend/app/ml/training.py` - outlier detection реализован
  - `detect_and_remove_outliers()` (строки 61-114)
  - Z-score метод с порогом 3σ
  - Интеграция в `prepare_training_data()` (строка 189)
  - Параметр `clean_outliers=True` в `train_all_models()` (строка 446)

- ✅ `scripts/retrain_problematic_branches.py` - скрипт готов
  - Автоматическое определение проблемных филиалов (wMAPE > 50%)
  - Переобучение с `clean_outliers=True` (строка 183)
  - Валидация результатов

## Как выполнить Phase 4: Валидация

### Шаг 1: Переобучить проблемные филиалы

Филиалы с критическими ошибками:
- **ID 166 (Суджанский район):** +1665% ошибка
- **ID 12 (МФЦ №1):** +288% ошибка

```bash
# Переобучить только проблемные филиалы
python3 scripts/retrain_problematic_branches.py --branch-ids 12,166 --workers 4

# Или переобучить все филиалы с wMAPE > 50%
python3 scripts/retrain_problematic_branches.py --mape-threshold 50 --workers 4
```

**Ожидаемый результат:**
- Модели пересохранятся в `models/branch_12_*.pkl` и `models/branch_166_*.pkl`
- Вывод покажет новые метрики валидации

### Шаг 2: Регенерировать прогнозы

```bash
# Регенерировать прогнозы для всех филиалов (с постобработкой)
python3 scripts/generate_forecast.py --month 2026-03 --workers 8

# Или только для проблемных
python3 scripts/generate_forecast.py --month 2026-03 --branch-id 166
python3 scripts/generate_forecast.py --month 2026-03 --branch-id 12
```

**Ожидаемый результат:**
- Таблица `forecasts` обновится с новыми прогнозами
- Прогнозы будут ограничены capacity constraints
- Логи покажут "[postprocessed]" метку

### Шаг 3: Запустить комплексный анализ

```bash
# Анализ качества прогнозов для всех филиалов
python3 scripts/comprehensive_data_analysis.py > docs/IMPROVEMENT_REPORT.md
```

**Что должен показать отчет:**
- Метрики по каждому филиалу (wMAPE, MAE, Peak accuracy)
- Сравнение с baseline (было/стало)
- Процент филиалов с ошибкой <25%

### Шаг 4: Сравнить с baseline метриками

**Baseline метрики (ДО улучшений):**
- 67% филиалов имеют wMAPE > 50%
- 33% филиалов имеют wMAPE < 25%
- Филиал 166: +1665% ошибка
- Филиал 12: +288% ошибка

**Критерии успеха (ПОСЛЕ улучшений):**
- ✅ ≥60% филиалов имеют wMAPE < 25% (было 33%)
- ✅ Филиал 166: wMAPE < 100% (было 1665%)
- ✅ Филиал 12: wMAPE < 100% (было 288%)
- ✅ Средний wMAPE по сети < 30% (было >50%)

### Шаг 5: Создать итоговый отчет

Создайте файл `docs/IMPROVEMENT_SUMMARY.md` с результатами:

```markdown
# Итоги улучшения точности прогнозов

## Метрики ДО

- Филиалов с wMAPE < 25%: 33% (14 из 44)
- Филиал 166 (Суджанский): wMAPE = 1665%
- Филиал 12 (МФЦ №1): wMAPE = 288%
- Средний wMAPE: ~55%

## Метрики ПОСЛЕ

[ЗАПОЛНИТЬ ПОСЛЕ ВЫПОЛНЕНИЯ ШАГОВ 1-3]

- Филиалов с wMAPE < 25%: ___% (___ из 44)
- Филиал 166: wMAPE = ___%
- Филиал 12: wMAPE = ___%
- Средний wMAPE: ___%

## Примененные улучшения

1. **Phase 1:** Валидация метаданных филиалов
   - Создана таблица `branch_metadata` с validated window counts
   - Скрипт `validate_branch_metadata.py` извлек и верифицировал данные

2. **Phase 2:** Постобработка прогнозов
   - Capacity constraints на основе `branch_metadata.max_capacity`
   - Почасовые статистические границы (mean ± 2.5σ)
   - Сглаживание скользящим средним (window=3)
   - Детекция и коррекция outliers в прогнозах

3. **Phase 3:** Очистка обучающих данных
   - Детекция outliers методом Z-score (3σ)
   - Winsorization wait time данных на уровне P95
   - Переобучение моделей для проблемных филиалов

## Критические исправления

### Филиал 166 (Суджанский район)
- **Проблема:** Модель прогнозировала 500+ посещений/час при capacity ~125
- **Решение:** Capacity constraint + переобучение с outlier cleaning
- **Результат:** wMAPE снизился с 1665% до ___%

### Филиал 12 (МФЦ №1)
- **Проблема:** Завышенные прогнозы из-за outliers в истории
- **Решение:** Outlier cleaning + переобучение
- **Результат:** wMAPE снизился с 288% до ___%

## Тесты

Запустите тесты для проверки качества:

```bash
pytest tests/test_critical_improvements.py -v
```

Все P0 тесты должны пройти (GREEN).
```

### Шаг 6: Запустить тесты

```bash
# Запустить все критические тесты
pytest tests/test_critical_improvements.py -v

# Или конкретные P0 тесты
pytest tests/test_critical_improvements.py::test_capacity_constraint_all_branches -v
pytest tests/test_critical_improvements.py::test_outlier_cleaning_does_not_remove_too_much -v
pytest tests/test_critical_improvements.py::test_end_to_end_branch_166_forecast_correction -v
```

**Ожидаемый результат:** Все тесты PASSED (GREEN)

### Шаг 7: Коммит результатов

```bash
git add models/branch_12_*.pkl models/branch_166_*.pkl
git add docs/IMPROVEMENT_REPORT.md docs/IMPROVEMENT_SUMMARY.md
git commit -m "docs: add improvement validation report (Phase 4 complete)"
```

## Что делать если тесты не проходят

### Если тесты FAILED:

1. **Проверить логи** постобработки:
   ```bash
   python3 scripts/generate_forecast.py --month 2026-03 --branch-id 166 --log-level DEBUG
   ```

2. **Проверить метаданные** филиала:
   ```bash
   python3 -c "
   from backend.app.database import SessionLocal
   from backend.app.models import BranchMetadata
   db = SessionLocal()
   m = db.query(BranchMetadata).filter_by(branch_id=166).first()
   print(f'Max capacity: {m.max_capacity}' if m else 'No metadata')
   db.close()
   "
   ```

3. **Проверить прогнозы** в БД:
   ```bash
   python3 -c "
   from backend.app.database import SessionLocal
   from backend.app.models import Forecast
   from sqlalchemy import func
   db = SessionLocal()
   max_pred = db.query(func.max(Forecast.predicted_visits)).filter_by(branch_id=166).scalar()
   print(f'Max predicted visits: {max_pred}')
   db.close()
   "
   ```

4. **Переобучить заново** с debug логами:
   ```bash
   python3 scripts/retrain_problematic_branches.py --branch-ids 166 --workers 1 --log-level DEBUG
   ```

## Финальный чеклист

- [ ] Модели переобучены для филиалов 12 и 166
- [ ] Прогнозы регенерированы с `apply_postprocessing=True`
- [ ] Комплексный анализ выполнен (`comprehensive_data_analysis.py`)
- [ ] Метрики улучшились:
  - [ ] Филиал 166: wMAPE < 100%
  - [ ] Филиал 12: wMAPE < 100%
  - [ ] ≥60% филиалов с wMAPE < 25%
- [ ] Все P0 тесты проходят (GREEN)
- [ ] Отчет `IMPROVEMENT_SUMMARY.md` создан
- [ ] Результаты закоммичены в git

## Следующий шаг: Phase 5 (UI)

После завершения Phase 4 и подтверждения улучшений, передайте задачу frontend разработчику:

**Task:** Обновить UI для отображения:
- Индикатор "capacity utilization" на Branch Detail странице
- Метки "postprocessed" на прогнозах
- Warning если прогноз близок к capacity (>80%)
- Tooltip с информацией о количестве окон филиала
