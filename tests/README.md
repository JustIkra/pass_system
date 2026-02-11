# Test Suite

Комплект тестов для системы прогнозирования МФЦ.

## Структура

```
tests/
├── __init__.py                          # Package init
├── conftest.py                          # Общие фикстуры
├── test_critical_improvements.py        # P0 критические тесты (TDD red phase)
├── test_postprocessing.py               # Edge cases постобработки
└── test_training_data_cleaning.py       # Edge cases подготовки данных
```

## Установка зависимостей

```bash
pip install pytest pytest-cov sqlalchemy pandas numpy prophet
```

## Запуск тестов

### Все тесты

```bash
# Из корня проекта
pytest tests/

# С coverage
pytest --cov=backend/app tests/

# С подробным выводом
pytest -vv tests/
```

### Отдельный файл

```bash
pytest tests/test_critical_improvements.py
pytest tests/test_postprocessing.py
pytest tests/test_training_data_cleaning.py
```

### Конкретный тест

```bash
pytest tests/test_critical_improvements.py::test_end_to_end_branch_166_forecast_correction
```

### По маркерам

```bash
# Только быстрые тесты (без slow)
pytest -m "not slow" tests/

# Только unit тесты
pytest -m unit tests/

# Только integration тесты
pytest -m integration tests/
```

## TDD Workflow

### Phase 1: Red (текущий этап)

Все P0 тесты из `test_critical_improvements.py` должны **FAIL**:

```bash
pytest tests/test_critical_improvements.py
```

Ожидаемый результат: **5 тестов FAIL** (или skip для frontend теста).

### Phase 2: Green

После реализации Phase 1-5 тесты должны **PASS**:

1. **Phase 1**: Постобработка (`postprocessing.py`)
2. **Phase 2**: Очистка выбросов (`training.py`)
3. **Phase 3**: Capacity constraint (`postprocessing.py`)
4. **Phase 4**: API enhancement (`schemas.py`, `forecast_service.py`)
5. **Phase 5**: Frontend quality badge

### Phase 3: Refactor

После прохождения всех тестов можно рефакторить код, поддерживая зеленое состояние.

## P0 Критические тесты

### 1. `test_end_to_end_branch_166_forecast_correction`

**Цель**: Прогноз для проблемного филиала 166 улучшился.

**Критерии**:
- wMAPE улучшился на 10%+ (было ~40%, стало <30%)
- Нет прогнозов выше capacity (125 visits/hour)
- Все прогнозы неотрицательные

**Phase**: 1 (Postprocessing) + 3 (Capacity)

### 2. `test_capacity_constraint_all_branches`

**Цель**: Все филиалы соблюдают capacity constraint.

**Критерии**:
- `max(predicted_visits) <= branch_capacity`
- Capacity = `num_windows * 25`

**Phase**: 3 (Capacity constraint)

### 3. `test_api_forecast_quality_field_present`

**Цель**: API возвращает quality_metrics.

**Критерии**:
- Response включает `quality_metrics` объект
- Содержит: `wmape`, `corrections_applied`, `outliers_removed`

**Phase**: 4 (API enhancement)

### 4. `test_frontend_quality_badge_renders`

**Цель**: Frontend отображает quality badge.

**Статус**: Skipped (frontend E2E тест, будет в Playwright)

**Phase**: 5 (Frontend)

### 5. `test_outlier_cleaning_does_not_remove_too_much`

**Цель**: Outlier cleaning удаляет <10% данных.

**Критерии**:
- P95 winsorization сохраняет все точки (только clip)
- Легитимные пики сохранены

**Phase**: 2 (Outlier cleaning)

**Статус**: Может PASS уже сейчас (P95 clipping уже есть)

## Edge Case Tests

### `test_postprocessing.py` (12 тестов)

- `test_capacity_zero_windows` - филиал без окон
- `test_capacity_no_data` - филиал без данных
- `test_historical_bounds_zero_variance` - все значения одинаковые
- `test_hourly_bounds_no_data_for_hour` - нет данных для часа
- `test_apply_constraints_empty_predictions` - пустой массив
- `test_smooth_predictions_insufficient_data` - <3 точек
- `test_smooth_predictions_preserves_edges` - края сохранены
- `test_detect_outliers_constant_predictions` - константа
- `test_detect_outliers_single_extreme` - 1 экстремальный выброс
- `test_detect_outliers_too_few_points` - <3 точек
- `test_postprocess_empty_dataframe` - пустой DF
- `test_postprocess_single_point` - 1 точка

### `test_training_data_cleaning.py` (13 тестов)

- `test_prepare_data_insufficient_points` - <360 точек
- `test_prepare_data_no_data` - пустая БД
- `test_prepare_data_all_outliers_wait_time` - все значения выбросы
- `test_prepare_data_iqr_equals_zero` - IQR=0
- `test_prepare_data_zero_visits_hours` - часы с 0 посещений
- `test_prepare_data_single_extreme_outlier_wait` - 1 экстремальный выброс
- `test_prepare_data_missing_hourly_slots` - пропуски в данных
- `test_prepare_data_sunday_skipped` - воскресенья пропущены
- `test_prepare_data_log_transform_applied` - log1p применен
- `test_prepare_data_wait_cap_stored` - log_cap сохранен
- `test_prepare_data_regressors_added` - все регрессоры добавлены
- `test_prepare_data_original_count_tracked` - original_count отслежен
- `test_prepare_data_null_wait_time_handling` - NULL обработан как 0

## Coverage

Целевое покрытие: **80%+** для критичных модулей:

- `backend/app/ml/training.py`
- `backend/app/ml/postprocessing.py`
- `backend/app/ml/utils.py`
- `backend/app/services/forecast_service.py`

Проверка coverage:

```bash
pytest --cov=backend/app/ml --cov-report=html tests/
open htmlcov/index.html
```

## CI/CD Integration

Добавить в `.github/workflows/test.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r backend/requirements.txt
      - run: pip install pytest pytest-cov
      - run: pytest --cov=backend/app tests/
```

## Troubleshooting

### Import errors

Убедитесь, что `backend/` в `PYTHONPATH`:

```bash
export PYTHONPATH="${PYTHONPATH}:/Users/maksim/git_projects/pass_system/backend"
pytest tests/
```

Или используйте `conftest.py` (уже настроен).

### Database errors

Тесты используют in-memory SQLite, но если нужна реальная БД:

```python
@pytest.fixture
def db_session():
    engine = create_engine("postgresql://localhost/mfc_test")
    # ...
```

### Slow tests

Отключите медленные тесты:

```bash
pytest -m "not slow" tests/
```
