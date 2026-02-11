# Phase 2-4 Implementation Status

**Дата:** 2026-02-10
**Статус:** Код реализован ✅, требуется валидация ❌

---

## Executive Summary

Все компоненты Phase 2-4 **уже реализованы** в кодовой базе. Необходимо выполнить только Phase 4 (валидация и метрики), так как:

- ✅ Phase 2 (Постобработка прогнозов) - код написан и интегрирован
- ✅ Phase 3 (Очистка обучающих данных) - outlier detection реализован
- ❌ Phase 4 (Валидация улучшений) - требуется запуск скриптов и сбор метрик

---

## Phase 2: Постобработка прогнозов ✅ COMPLETE

### Task 2.1: Интеграция постобработки ✅

**Реализованные файлы:**

1. **`backend/app/ml/postprocessing.py`** - полная реализация
   - Строки 9-52: `get_branch_capacity()` - capacity из validated metadata
   - Строки 54-83: `get_historical_bounds()` - статистические границы (mean ± 3σ)
   - Строки 85-116: `get_hourly_bounds()` - почасовые паттерны (mean ± 2.5σ)
   - Строки 118-156: `apply_constraints()` - применение ограничений
   - Строки 158-180: `smooth_predictions()` - сглаживание скользящим средним
   - Строки 182-207: `detect_outliers_in_predictions()` - детекция аномалий
   - Строки 209-270: `postprocess_forecast()` - полный pipeline постобработки

2. **`backend/app/ml/prediction.py`** - интеграция выполнена
   - Строка 38: `from app.ml.postprocessing import postprocess_forecast`
   - Строки 195-196: параметр `apply_postprocessing: bool = True`
   - Строки 272-288: применение в `generate_forecast()`
   - Строки 410-426: применение в `generate_forecast_range()`

3. **`scripts/generate_forecast.py`** - использует постобработку
   - Строки 82, 114: передача `apply_postprocessing=True` в worker процессы
   - Строки 335, 340: передача `apply_postprocessing=True` в sequential режиме

**Ключевые возможности:**

```python
# Capacity constraint (жесткое ограничение)
capacity = get_branch_capacity(db, branch_id)  # Из branch_metadata
predictions = np.minimum(predictions, capacity)

# Statistical bounds (мягкое ограничение)
lower, upper = get_hourly_bounds(db, branch_id, hour)
predictions = np.clip(predictions, lower, upper)

# Smoothing (устранение резких скачков)
smoothed = smooth_predictions(predictions, window=3)
```

**Приоритет источников данных для capacity:**
1. `branch_metadata.max_capacity` (валидированные данные) - **высший приоритет**
2. `MAX(hourly_stats.num_windows_active) * 25` (исторические данные)
3. `MAX(hourly_stats.total_visits) * 1.2` (fallback с запасом 20%)

### Task 2.2: Визуализация эффекта ⚠️ OPTIONAL

**Статус:** Не реализовано (низкий приоритет)

Можно создать скрипт `scripts/visualize_postprocessing_effect.py` для визуализации, но это необязательно для Phase 4.

---

## Phase 3: Очистка обучающих данных ✅ COMPLETE

### Task 3.1: Outlier detection ✅

**Реализованные файлы:**

1. **`backend/app/ml/training.py`** - outlier detection реализован
   - Строки 61-115: `detect_and_remove_outliers()` - Z-score метод
   - Строка 122: параметр `clean_outliers: bool = True` в `prepare_training_data()`
   - Строка 189: `df = detect_and_remove_outliers(df, y_col="y", threshold=3.0)`
   - Строка 446: параметр `clean_outliers: bool = True` в `train_all_models()`

**Алгоритм очистки:**

```python
def detect_and_remove_outliers(df, y_col="y", threshold=3.0):
    """
    Удаляет outliers используя Z-score метод.

    - Вычисляет Z-score только для non-zero значений
    - Удаляет точки с |Z-score| > threshold (default: 3σ)
    - Сохраняет нулевые значения (закрытые часы)
    """
    non_zero = values[values > 0]
    mean = np.mean(non_zero)
    std = np.std(non_zero)
    z_scores = np.abs((values - mean) / std)
    mask = (values == 0) | (z_scores <= threshold)
    return df[mask].copy()
```

**Дополнительная обработка wait time:**

- Строки 195-200: Winsorization на уровне P95 для wait time данных
- Защита от экстремальных outliers (max ~467 мин, P99 ~24 мин)

### Task 3.2: Переобучение проблемных филиалов ✅

**Реализованные файлы:**

1. **`scripts/retrain_problematic_branches.py`** - полная реализация
   - Строки 95-122: `identify_problematic_branches()` - определение по wMAPE
   - Строки 136-152: автоматический или ручной выбор филиалов
   - Строки 175-184: вызов `train_all_models()` с `clean_outliers=True`
   - Строки 199-220: вывод метрик валидации

**Использование:**

```bash
# Переобучить проблемные филиалы (wMAPE > 50%)
python3 scripts/retrain_problematic_branches.py --mape-threshold 50

# Переобучить конкретные филиалы
python3 scripts/retrain_problematic_branches.py --branch-ids 12,166
```

---

## Phase 4: Валидация улучшений ❌ TODO

### Что НЕ выполнено:

1. ❌ Переобучение моделей для филиалов 12 и 166 с `clean_outliers=True`
2. ❌ Регенерация прогнозов для 2026-03 с `apply_postprocessing=True`
3. ❌ Запуск `comprehensive_data_analysis.py` для сбора метрик
4. ❌ Создание отчета `IMPROVEMENT_SUMMARY.md` с результатами
5. ❌ Запуск тестов `test_critical_improvements.py`

### Что нужно сделать:

См. детальные инструкции в **`docs/PHASE_4_VALIDATION_INSTRUCTIONS.md`**

**Краткий чеклист:**

```bash
# 1. Проверить статус
python3 scripts/check_improvements_status.py

# 2. Переобучить проблемные филиалы
python3 scripts/retrain_problematic_branches.py --branch-ids 12,166 --workers 4

# 3. Регенерировать прогнозы
python3 scripts/generate_forecast.py --month 2026-03 --workers 8

# 4. Запустить анализ
python3 scripts/comprehensive_data_analysis.py > docs/IMPROVEMENT_REPORT.md

# 5. Запустить тесты
pytest tests/test_critical_improvements.py -v

# 6. Создать итоговый отчет
# Заполнить docs/IMPROVEMENT_SUMMARY.md
```

---

## Baseline метрики (ДО улучшений)

Из документа `docs/plans/2026-02-10-improve-forecast-accuracy.md`:

- **67% филиалов** имеют wMAPE > 50% (плохое качество)
- **33% филиалов** имеют wMAPE < 25% (приемлемое качество)
- **Филиал 166 (Суджанский район):** wMAPE = 1665% (+1665% ошибка)
- **Филиал 12 (МФЦ №1):** wMAPE = 288% (+288% ошибка)

### Причины ошибок:

**Филиал 166:**
- Модель прогнозировала 500+ посещений/час
- Capacity филиала ~125 (5 окон × 25 клиентов/окно)
- Прогноз в 4 раза выше физически возможного

**Филиал 12:**
- Outliers в обучающих данных искажали модель
- Отсутствие ограничений на прогнозы

---

## Ожидаемые метрики (ПОСЛЕ улучшений)

### Критерии успеха Phase 2-4:

- ✅ **≥60% филиалов** имеют wMAPE < 25% (было 33%)
- ✅ **Филиал 166:** wMAPE < 100% (было 1665%)
- ✅ **Филиал 12:** wMAPE < 100% (было 288%)
- ✅ **Средний wMAPE:** < 30% (было ~55%)

### Механизмы улучшения:

1. **Capacity constraints** предотвратят прогнозы выше физических возможностей
2. **Outlier cleaning** уберет аномальные точки из обучающих данных
3. **Statistical bounds** ограничат прогнозы в разумных пределах (mean ± 2.5σ)
4. **Smoothing** устранит резкие скачки между часами

---

## Тесты (P0 Critical)

Все тесты находятся в **`tests/test_critical_improvements.py`**

### Список P0 тестов:

1. **`test_end_to_end_branch_166_forecast_correction`**
   - Проверяет: wMAPE улучшился, нет превышения capacity
   - Филиал: 166 (Суджанский район)

2. **`test_capacity_constraint_all_branches`**
   - Проверяет: все прогнозы ≤ branch_metadata.max_capacity
   - Филиалы: все с метаданными

3. **`test_outlier_cleaning_does_not_remove_too_much`**
   - Проверяет: удаляется <10% обучающих данных
   - Филиалы: 12, 166

4. **`test_postprocessing_smooths_predictions`**
   - Проверяет: smoothing уменьшает резкие скачки
   - Филиалы: любые

5. **`test_statistical_bounds_are_reasonable`**
   - Проверяет: границы в пределах mean ± 3σ
   - Филиалы: любые

**Запуск:**

```bash
pytest tests/test_critical_improvements.py -v
```

**Ожидаемый результат:** Все тесты PASSED (GREEN)

---

## Архитектурные решения

### 1. Постобработка vs Model Retraining

**Решение:** Комбинированный подход

- **Постобработка** (fast, runtime) - для capacity constraints и smoothing
- **Model retraining** (slow, offline) - для устранения outliers из истории

**Обоснование:**
- Capacity constraints не могут быть внедрены в Prophet (модель не знает о физических ограничениях)
- Outlier cleaning улучшает качество модели с источника (лучше чем постобработка)

### 2. Приоритет источников данных для capacity

**Решение:** Трехуровневая иерархия

1. **branch_metadata.max_capacity** - валидированные данные (высший приоритет)
2. **hourly_stats aggregations** - исторические данные
3. **Fallback значения** - консервативные оценки

**Обоснование:**
- Разные источники дают разные результаты (см. `BRANCH_METADATA_DISCREPANCIES.md`)
- Валидированные метаданные вручную проверены QA
- Fallback защищает от ошибок при отсутствии данных

### 3. Z-score vs IQR для outlier detection

**Решение:** Z-score метод с порогом 3σ

**Обоснование:**
- IQR чувствителен к асимметрии (MFC данные асимметричны - много нулей)
- Z-score работает на non-zero значениях, пропускает нули (закрытые часы)
- Порог 3σ = 99.7% данных сохраняется (очень консервативно)

### 4. Smoothing window size

**Решение:** Window = 3 часа

**Обоснование:**
- Слишком большое окно (>3) затирает реальные пики (например, обеденный час)
- Слишком малое окно (<3) не устраняет скачки
- Window = 3 - баланс между smoothing и сохранением паттернов

---

## Известные ограничения

### 1. Постобработка применяется к predicted_visits, но не к wait time

**Причина:** Wait time модель использует logistic growth с cap (уже ограничен)

**Риск:** Низкий (wait time прогнозы не имеют критических outliers)

### 2. Outlier detection не различает реальные пики и аномалии

**Пример:** Пик посещений в день выдачи паспортов может быть удален как outlier

**Mitigation:** Консервативный порог 3σ минимизирует false positives

### 3. Capacity constraints могут занижать прогнозы в периоды перегрузки

**Пример:** Если филиал реально работает на 120% capacity (очереди), прогноз будет ограничен 100%

**Обоснование:** Прогноз должен показывать разумные ожидания, а не хаос перегрузки

---

## Файловая структура

```
backend/app/
├── ml/
│   ├── postprocessing.py      ✅ Phase 2 - постобработка прогнозов
│   ├── prediction.py          ✅ Интегрирован postprocess_forecast
│   └── training.py            ✅ Phase 3 - outlier detection
├── services/
│   └── branch_metadata.py     ✅ Phase 1 - валидация метаданных
└── models.py                  ✅ BranchMetadata модель

scripts/
├── validate_branch_metadata.py        ✅ Phase 1 - валидация
├── retrain_problematic_branches.py    ✅ Phase 3 - переобучение
├── generate_forecast.py               ✅ Использует postprocessing
├── comprehensive_data_analysis.py     ❌ Нужно запустить для метрик
└── check_improvements_status.py       ✅ NEW - проверка статуса

tests/
└── test_critical_improvements.py      ❌ Нужно запустить (P0 тесты)

docs/
├── plans/2026-02-10-improve-forecast-accuracy.md  ✅ План Phase 1-5
├── PHASE_4_VALIDATION_INSTRUCTIONS.md             ✅ NEW - инструкции
├── PHASE_2-4_IMPLEMENTATION_STATUS.md             ✅ NEW - этот документ
├── IMPROVEMENT_REPORT.md                          ❌ TODO - создать после анализа
└── IMPROVEMENT_SUMMARY.md                         ❌ TODO - итоговый отчет
```

---

## Следующие действия

### Для Software Engineer (вы):

1. ✅ Прочитать `docs/PHASE_4_VALIDATION_INSTRUCTIONS.md`
2. ⏳ Запустить `python3 scripts/check_improvements_status.py` для проверки
3. ⏳ Выполнить Phase 4 согласно инструкциям
4. ⏳ Создать `docs/IMPROVEMENT_SUMMARY.md` с метриками

### Для QA Engineer:

1. Запустить тесты `pytest tests/test_critical_improvements.py -v`
2. Проверить что все P0 тесты в GREEN состоянии
3. Верифицировать метрики в `IMPROVEMENT_REPORT.md`

### Для Frontend Developer (Phase 5):

1. Ждать завершения Phase 4
2. Получить confirmed метрики улучшений
3. Реализовать UI индикаторы capacity utilization

---

## Вопросы и ответы

### Q: Почему код уже написан, но Phase 2-4 не завершены?

**A:** Код написан (implementation), но не проверен (validation). Phase 4 требует:
- Запуска скриптов на реальных данных
- Сбора метрик и создания отчетов
- Подтверждения что метрики улучшились

### Q: Можно ли пропустить Phase 4 и сразу перейти к Phase 5 (UI)?

**A:** Нет. Phase 4 критична для подтверждения что улучшения работают. Без метрик:
- Невозможно доказать что проблема решена
- UI может показывать неверные индикаторы
- Нет baseline для мониторинга в production

### Q: Что если метрики Phase 4 не улучшились?

**A:** Нужно debug:
1. Проверить что metadata корректны (`validate_branch_metadata.py`)
2. Проверить что постобработка применяется (`apply_postprocessing=True`)
3. Проверить логи переобучения (outliers удалены?)
4. При необходимости - tuning порогов (3σ → 2.5σ, capacity margin и т.д.)

### Q: Как часто нужно переобучать модели?

**A:** Рекомендации:
- **Регулярное переобучение:** 1 раз в квартал (новые данные)
- **Проблемные филиалы:** по запросу при wMAPE > 50%
- **Изменение метаданных:** после обновления num_windows (ремонт, новые окна)

---

## Changelog

**2026-02-10:**
- Создан отчет о статусе Phase 2-4
- Все компоненты реализованы, ожидается валидация
- Созданы helper скрипты: `check_improvements_status.py`
- Созданы инструкции: `PHASE_4_VALIDATION_INSTRUCTIONS.md`
