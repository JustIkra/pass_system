# Test Plan: Система прогнозирования загрузки окон МФЦ

**Версия:** 1.0
**Дата:** 2026-02-09
**Статус:** Draft
**Связанные документы:** [Product Vision](product_vision.md), [Technical Requirements](technical_requirements.md)

---

## 1. Стратегия тестирования

| Уровень | Инструмент | Область покрытия | Когда запускать |
|---------|------------|------------------|-----------------|
| **Unit tests** (backend) | pytest | ETL-парсинг, ML-функции, бизнес-логика сервисов | На каждый коммит |
| **Unit tests** (frontend) | vitest / jest | Компоненты, хуки, утилиты | На каждый коммит |
| **Integration tests** | pytest + httpx (AsyncClient) | API endpoints (FastAPI TestClient) | На каждый коммит |
| **E2E tests** | Playwright (опционально, в MVP можно упростить) | Основные пользовательские сценарии | Перед релизом |
| **ML validation** | pytest + собственный backtesting-модуль | Метрики качества моделей (MAPE, MAE, peak accuracy) | После переобучения модели |

**Принцип пирамиды:** основной объем покрытия обеспечивают unit и integration тесты. E2E -- только критические сценарии.

**Тестовые данные:**
- Для unit тестов: фикстуры с минимальными CSV-фрагментами (5-10 строк)
- Для integration тестов: тестовая SQLite БД, заполненная фикстурами
- Для ML validation: реальные данные за период 2023-01 -- 2024-02 (train/test split по 2023-10-01)

---

## 2. Backend тесты

### 2.1 ETL тесты

**Файл:** `backend/tests/test_etl.py`

| ID теста | Описание | Входные данные | Ожидаемый результат |
|----------|----------|----------------|---------------------|
| `test_csv_parsing` | Корректный парсинг CSV с разделителем `;` | CSV-фрагмент с 5 строками Статистики ЭО (разделитель `;`) | Все 5 записей распарсены, поля соответствуют маппингу колонок |
| `test_date_parsing` | Парсинг дат формата DD.MM.YYYY -> datetime | Строки `"15.03.2023"`, `"01.01.2024"` | `datetime(2023, 3, 15)`, `datetime(2024, 1, 1)` |
| `test_time_parsing` | Парсинг времени HH:MM:SS -> timedelta (секунды) | Строки `"09:30:15"`, `"00:05:42"` | `timedelta(hours=9, minutes=30, seconds=15)`, `timedelta(minutes=5, seconds=42)` |
| `test_empty_values` | Обработка пустых полей (пустое `Employee_window`, пустое `Time_priem`) | CSV-строка с пустыми `Employee_window` и `Time_priem` | `employee_window = NULL`, `service_duration = NULL` в БД |
| `test_null_string_handling` | Строка `"NULL"` в справочнике филиалов интерпретируется как NULL | CSV справочника филиалов с `Depart_id = "NULL"` | `depart_id = NULL` в БД |
| `test_duplicate_handling` | Дубликаты специалистов разрешаются через UPSERT (последняя запись побеждает) | Два CSV-файла справочника сотрудников с одинаковым `Employee_ID` и разными `Post` | В БД одна запись с `Post` из второго (более позднего) файла |
| `test_load_all_months` | Загрузка всех 14 файлов Статистики ЭО без ошибок | 14 CSV-файлов (2023-01 .. 2024-02) | Все файлы загружены, лог не содержит ошибок (допускаются skipped строки) |
| `test_data_integrity` | Количество записей в БД соответствует количеству строк в CSV (минус заголовок) | Один CSV-файл с известным количеством строк (например, 100) | `SELECT COUNT(*) FROM queue_records` = 100 (за вычетом ошибочных строк) |
| `test_quoted_csv_parsing` | Парсинг CSV с двойными кавычками вокруг значений (справочники) | CSV-фрагмент справочника с кавычками | Значения корректно извлечены без лишних кавычек |
| `test_load_order` | Порядок загрузки: branches -> services -> employees -> queue_records -> employee_roles -> employee_services | Полный набор фикстур | FK-ограничения не нарушены, все записи загружены |
| `test_hourly_stats_aggregation` | Агрегация queue_records в hourly_stats | 20 записей queue_records для одного филиала за один день | `hourly_stats` содержит записи для часов 8-19 с корректными `total_visits`, `avg_wait_minutes` |
| `test_wait_duration_seconds` | `wait_duration` и `service_duration` хранятся в секундах | CSV-строка с `Time_wait_vizov = "00:15:30"` | `wait_duration = 930` (секунды) |

---

### 2.2 API тесты

**Файл:** `backend/tests/test_api.py`

| ID теста | Endpoint | Описание | Ожидаемый результат |
|----------|----------|----------|---------------------|
| `test_health_check` | `GET /health` | Healthcheck-эндпоинт | 200 OK |
| `test_get_branches` | `GET /api/branches` | Список филиалов | 200, массив >= 44 элементов, каждый содержит `id`, `name`, `total_records`, `date_range` |
| `test_get_branch_detail` | `GET /api/branches/176` | Детали филиала | 200, объект с `id=176`, `name`, `num_employees`, `num_windows`, `avg_daily_visits`, `avg_wait_minutes`, `top_services` |
| `test_get_forecast` | `GET /api/branches/176/forecast?month=2026-03` | Прогноз загрузки | 200, `data` содержит записи для каждого рабочего дня месяца и каждого часа (8-19), `summary` заполнен |
| `test_forecast_values_positive` | `GET /api/branches/176/forecast?month=2026-03` | Все прогнозные значения неотрицательные | Для всех точек: `predicted_visits >= 0`, `predicted_avg_wait >= 0` |
| `test_forecast_confidence` | `GET /api/branches/176/forecast?month=2026-03` | Доверительный интервал корректен | Для всех точек: `confidence_lower <= predicted_visits <= confidence_upper` |
| `test_windows_load` | `GET /api/branches/176/windows?month=2026-03` | Данные по окнам филиала | 200, массив `windows` с `window_number`, `avg_daily_load_percent`, `load_by_hour`, `status` |
| `test_windows_status_values` | `GET /api/branches/176/windows?month=2026-03` | Статус окон из допустимого набора | Все `status` принадлежат `{"overloaded", "normal", "underloaded", "idle"}` |
| `test_staffing` | `GET /api/branches/176/staffing?month=2026-03` | Рекомендации по штату | 200, `recommendations` содержит значения для каждого рабочего дня x часа (8-19), поля `required_windows`, `delta`, `status` |
| `test_staffing_status_values` | `GET /api/branches/176/staffing?month=2026-03` | Статус штата из допустимого набора | Все `status` принадлежат `{"understaffed", "optimal", "overstaffed"}` |
| `test_compare_branches` | `GET /api/branches/compare?ids=1,2,3&month=2026-03` | Сравнение 3 филиалов | 200, `branches` содержит ровно 3 элемента с `predicted_total_visits`, `predicted_avg_wait`, `predicted_peak_hour` |
| `test_compare_too_few` | `GET /api/branches/compare?ids=1&month=2026-03` | Менее 2 филиалов | 400, `{"detail": "Provide 2-5 branch IDs"}` |
| `test_compare_too_many` | `GET /api/branches/compare?ids=1,2,3,4,5,6&month=2026-03` | Более 5 филиалов | 400 |
| `test_overview` | `GET /api/analytics/overview?month=2026-03` | Общая сводка по сети | 200, `total_branches = 44`, `total_predicted_visits > 0`, массивы `top_overloaded` и `top_underloaded` |
| `test_history` | `GET /api/branches/176/history?from=2023-01&to=2024-02` | Исторические данные | 200, массивы `daily` и `hourly` не пустые, даты в пределах запрошенного периода |
| `test_invalid_branch` | `GET /api/branches/999999` | Несуществующий филиал | 404, `{"detail": "Branch not found"}` |
| `test_invalid_month_format` | `GET /api/branches/176/forecast?month=abc` | Неверный формат месяца | 422 |
| `test_invalid_month_value` | `GET /api/branches/176/forecast?month=2026-13` | Невалидный месяц (13) | 422 |
| `test_missing_month_param` | `GET /api/branches/176/forecast` | Отсутствует обязательный параметр `month` | 422 |
| `test_upload_csv` | `POST /api/data/upload` (multipart) | Загрузка валидного CSV | 200, `records_loaded > 0`, `status = "ok"` |
| `test_upload_invalid_csv` | `POST /api/data/upload` (multipart) | Загрузка CSV с неверными колонками | 400, `{"detail": "Invalid CSV format"}` |
| `test_model_retrain` | `POST /api/model/retrain` | Запуск переобучения | 202, `{"status": "training_started"}` |
| `test_model_status` | `GET /api/model/status` | Статус обучения модели | 200, объект с `status`, `progress`, `total_branches` |
| `test_swagger_docs` | `GET /docs` | Swagger UI доступен | 200 |
| `test_cors_headers` | `OPTIONS /api/branches` | CORS заголовки | Ответ содержит `Access-Control-Allow-Origin` для `http://localhost:5173` |
| `test_response_time` | `GET /api/branches/176/forecast?month=2026-03` | Время ответа < 2 секунд | Ответ получен менее чем за 2000 мс |

---

### 2.3 ML тесты

**Файл:** `backend/tests/test_ml.py`

| ID теста | Описание | Входные данные | Ожидаемый результат |
|----------|----------|----------------|---------------------|
| `test_model_training` | Модель обучается без ошибок для каждого филиала | Данные `hourly_stats` для филиала 176 (>= 100 точек) | `model.fit()` завершается без исключений, модель сериализуется через joblib |
| `test_model_skip_insufficient_data` | Филиал с < 100 точками пропускается с warning | Данные с 50 точками | Модель не обучена, записан warning в лог |
| `test_prediction_shape` | Прогноз имеет правильную форму (рабочие дни x часы 8-19) | Обученная модель, month=`"2026-03"` | DataFrame содержит по 12 записей (08:00-19:00) на каждый рабочий день марта 2026 |
| `test_mape_threshold` | MAPE < 20% на тестовых данных (2023-10 -- 2024-02) | Train: 2023-01 -- 2023-09, Test: 2023-10 -- 2024-02 | `MAPE < 20%` для >= 80% филиалов |
| `test_mae_wait_threshold` | MAE по времени ожидания < 5 минут | Train/test split по 2023-10-01 | `MAE < 5 мин` для >= 80% филиалов |
| `test_peak_accuracy` | Точность определения пиков (top-3 часа за неделю) > 70% | Train/test split по 2023-10-01 | >= 70% совпадений: 2 из 3 самых загруженных часов угаданы |
| `test_no_negative_predictions` | Все предсказания >= 0 | Прогноз для филиала 176 на месяц | Все значения `yhat >= 0` после post-processing |
| `test_seasonal_patterns` | Модель воспроизводит недельную сезонность (понедельник > воскресенье) | Прогноз на типичную рабочую неделю | `predicted_visits(Monday) > predicted_visits(Sunday)` для рабочего филиала |
| `test_confidence_interval_width` | Доверительный интервал имеет разумную ширину | Прогноз для филиала 176 | `confidence_upper - confidence_lower > 0` и `< 3 * predicted_visits` |
| `test_ci_coverage` | Coverage доверительного интервала (80% CI) > 75% на test data | Факт vs прогноз на тестовом периоде | >= 75% фактических значений попадают в интервал `[yhat_lower, yhat_upper]` |
| `test_holiday_effect` | Модель учитывает праздники РФ (снижение трафика) | Прогноз на январь (1-8 -- каникулы) | `predicted_visits` для 1-8 января ниже, чем для 10-15 января |
| `test_feature_engineering` | `prepare_prophet_data()` возвращает корректный DataFrame | Данные `hourly_stats` для филиала 176 | DataFrame содержит колонки `[ds, y, day_of_week, month, is_holiday, is_month_start, is_month_end, is_monday]`, нет NaN в `y` |
| `test_model_serialization` | Модель корректно сохраняется и загружается | Обученная модель | `joblib.dump()` + `joblib.load()` -> прогноз идентичен |
| `test_forecast_caching` | Повторный запрос прогноза возвращает кэшированный результат | Два вызова `predict(branch_id, month)` | Второй вызов < 100 мс, результаты идентичны |
| `test_cache_invalidation` | Кэш инвалидируется после переобучения | `invalidate_cache()` -> повторный `predict()` | Прогноз пересчитан (timestamp `created_at` обновлен) |

---

## 3. Frontend тесты

### 3.1 Компоненты

**Файл:** `frontend/src/components/__tests__/`

| ID теста | Компонент | Описание | Ожидаемый результат |
|----------|-----------|----------|---------------------|
| `test_branch_list_renders` | `BranchSelector` | Список филиалов рендерится | Отрисовано >= 44 элементов, каждый содержит `name` |
| `test_branch_filter` | `BranchSelector` | Фильтр по имени работает | При вводе "Конышев" отображается только "Филиал Конышевский район" |
| `test_heatmap_colors` | `HeatmapChart` | Цвета соответствуют уровням загрузки | Ячейки с высокими значениями окрашены в красный, с низкими -- в зеленый |
| `test_heatmap_dimensions` | `HeatmapChart` | Сетка 7x12 (дни недели x часы) | Рендерится 7 строк (Пн-Вс) и 12 колонок (08:00-19:00) |
| `test_heatmap_tooltip` | `HeatmapChart` | Tooltip отображает день недели, час и значение | При наведении на ячейку показывается tooltip с данными |
| `test_load_indicator_overloaded` | `LoadIndicator` | Красный цвет для загрузки > 85% | `value=90` -> фон `#EF4444`, текст "overloaded" |
| `test_load_indicator_normal` | `LoadIndicator` | Желтый цвет для загрузки 50-85% | `value=70` -> фон `#FBBF24` |
| `test_load_indicator_underloaded` | `LoadIndicator` | Зеленый цвет для загрузки 20-50% | `value=35` -> фон `#10B981` |
| `test_load_indicator_idle` | `LoadIndicator` | Серый цвет для загрузки < 20% | `value=10` -> фон `#D1D5DB` |
| `test_month_selector` | `MonthPicker` | Переключение месяца вызывает callback | Выбор "2026-04" -> `onChange("2026-04")` вызван |
| `test_line_chart_renders` | `LineChart` | График рендерится с данными и confidence interval | Линия и область доверительного интервала видны |
| `test_line_chart_empty` | `LineChart` | Корректный empty state при отсутствии данных | Показано сообщение "Нет данных" |
| `test_staffing_table_colors` | `StaffingTable` | Ячейки окрашены по delta | `delta >= 2` -> красный, `delta == 1` -> желтый, `delta <= 0` -> зеленый |
| `test_bar_chart_sorting` | `BarChart` | Бары отсортированы по убыванию значения | Первый бар имеет наибольшее значение |
| `test_loading_spinner` | Все компоненты | Показывается loading spinner во время загрузки данных | Spinner виден при `isLoading=true`, скрыт при `isLoading=false` |
| `test_error_state` | Все компоненты | Показывается сообщение об ошибке при неудачном запросе | При ошибке API отображается понятное сообщение |

---

### 3.2 Страницы

**Файл:** `frontend/src/pages/__tests__/`

| ID теста | Страница | Описание | Ожидаемый результат |
|----------|----------|----------|---------------------|
| `test_overview_loads` | `Overview` | Главная загружается и отображает KPI-карточки | Видны 4 KPI-карточки: "Всего обращений", "Ср. ожидание", "Перегруженных", "Простаивающих" |
| `test_overview_branch_table` | `Overview` | Таблица филиалов с поиском и сортировкой | Таблица содержит столбцы: ID, Название, Прогноз, Ожидание, Статус |
| `test_overview_top_lists` | `Overview` | Top-5 перегруженных и недогруженных | Отображены два списка по 5 филиалов |
| `test_branch_detail_loads` | `BranchDetail` | Страница филиала загружается с графиками | Видны: KPI-карточки (5 шт), LineChart, HeatmapChart, табы "Окна"/"Штат"/"История" |
| `test_windows_page_loads` | `Windows` | Страница окон отображает таблицу | Видна таблица окон с цветовой индикацией и легендой |
| `test_staffing_page_loads` | `Staffing` | Страница штата отображает матрицу | Видна матрица день x час с рекомендациями и цветовой индикацией |
| `test_compare_page_loads` | `Compare` | Страница сравнения с мультиселектом | Виден мультиселект филиалов (2-5), BarChart и таблица сравнения |
| `test_history_page_loads` | `History` | Страница истории с графиком факт vs прогноз | Видны: LineChart (два ряда), метрики MAPE/MAE, HeatmapChart |
| `test_navigation` | Все | Переход между страницами работает | Клик по филиалу на Overview -> `/branch/:id`, табы -> `/branch/:id/windows`, `/branch/:id/staffing` |
| `test_breadcrumbs` | `BranchDetail`, `Windows`, `Staffing` | Breadcrumbs отображаются и работают | "Главная > Филиал > Окна" -- клик по "Главная" ведет на `/` |
| `test_no_console_errors` | Все страницы | Нет `console.error` при рендере | `console.error` не вызван во время рендера каждой страницы |

---

## 4. Сценарии приемочного тестирования (Acceptance Tests)

### Сценарий 1: Руководитель просматривает прогноз

**User Story:** US-1 (Прогноз загрузки по филиалу)

| Шаг | Действие | Ожидаемый результат |
|-----|----------|---------------------|
| 1 | Открыть приложение (`http://localhost:3000`) | Видна главная страница с KPI-карточками и списком филиалов |
| 2 | Убедиться, что KPI-карточки заполнены | "Всего обращений" > 0, "Ср. ожидание" > 0 |
| 3 | Кликнуть на филиал "Конышевский район" | Открывается дашборд `/branch/176` с прогнозом |
| 4 | Проверить LineChart | Виден график обращений по дням с confidence interval |
| 5 | Проверить Heatmap | Heatmap корректно раскрашен: красные ячейки = часы с высокой загрузкой |
| 6 | Переключить месяц на "2026-04" | Данные на графиках обновляются, спиннер загрузки виден во время запроса |

---

### Сценарий 2: Менеджер смотрит окна

**User Story:** US-2 (Перегруженные и простаивающие окна)

| Шаг | Действие | Ожидаемый результат |
|-----|----------|---------------------|
| 1 | Открыть филиал -> перейти на вкладку "Окна" | Страница `/branch/176/windows` загружается |
| 2 | Проверить таблицу окон | Видна таблица с колонками: Окно, Ср. загрузка %, часы 08-19, Статус |
| 3 | Проверить цветовую индикацию | Перегруженные окна (> 85%) выделены красным |
| 4 | Проверить простаивающие окна | Простаивающие окна (< 20%) выделены серым |
| 5 | Проверить легенду | Легенда содержит 4 уровня: красный, желтый, зеленый, серый |

---

### Сценарий 3: Планировщик смотрит штат

**User Story:** US-3 (Рекомендации по штату)

| Шаг | Действие | Ожидаемый результат |
|-----|----------|---------------------|
| 1 | Открыть филиал -> вкладка "Штат" | Страница `/branch/176/staffing` загружается |
| 2 | Проверить матрицу день x час | Видна таблица с датами по строкам и часами 08-19 по колонкам |
| 3 | Проверить значения ячеек | Каждая ячейка содержит `required_windows` (целое число > 0) |
| 4 | Проверить цветовую индикацию | Дефицит >= 2 -- красный, дефицит 1 -- желтый, норма -- зеленый |
| 5 | Проверить summary | Отображается "Рекомендуется X окон в среднем (текущее: Y)" |

---

### Сценарий 4: Сравнение филиалов

**User Story:** US-4 (Сравнение филиалов)

| Шаг | Действие | Ожидаемый результат |
|-----|----------|---------------------|
| 1 | Перейти на страницу сравнения (`/compare`) | Виден мультиселект филиалов и MonthPicker |
| 2 | Выбрать 3 филиала | Выбраны 3 филиала в мультиселекте |
| 3 | Нажать "Сравнить" / данные загрузятся автоматически | Видна сводная таблица с метриками: обращения, ожидание, обслуживание, пик-час, окна |
| 4 | Проверить BarChart | Горизонтальные бары для 3 филиалов, отсортированные по значению |

---

### Сценарий 5: Загрузка и обучение (администратор)

| Шаг | Действие | Ожидаемый результат |
|-----|----------|---------------------|
| 1 | Запустить `python scripts/init_db.py --csv-dir ./data` | Скрипт выполняется без ошибок, выводит статистику загрузки |
| 2 | Проверить итоговую статистику | `queue_records >= 1,500,000`, `branches >= 44`, `hourly_stats >= 150,000` |
| 3 | Запустить `python scripts/train_model.py` | Обучены модели для >= 40 филиалов, файлы `*.pkl` созданы в `models/` |
| 4 | Запустить `python scripts/generate_forecast.py --month 2026-03` | Таблица `forecasts` заполнена для всех филиалов |
| 5 | Проверить API: `GET /api/branches/176/forecast?month=2026-03` | 200 OK, данные прогноза возвращены |

---

## 5. Критерии Definition of Done (общие)

### Функциональные критерии

- [ ] Все unit тесты проходят (`pytest backend/tests/` -- 0 failures)
- [ ] Все integration тесты проходят (`pytest backend/tests/test_api.py` -- 0 failures)
- [ ] Frontend тесты проходят (`npm test` -- 0 failures)
- [ ] MAPE модели < 20% для >= 80% филиалов на test data (2023-10 -- 2024-02)
- [ ] MAE по времени ожидания < 5 минут для >= 80% филиалов
- [ ] Точность определения пиков > 70%

### Нефункциональные критерии

- [ ] API отвечает за < 2 секунды на прогноз (первый запрос)
- [ ] API отвечает за < 100 мс на прогноз из кэша (повторный запрос)
- [ ] Время загрузки страницы < 3 секунды
- [ ] Время обучения всех моделей < 30 минут
- [ ] Загрузка CSV (init_db) < 10 минут

### Инфраструктурные критерии

- [ ] Приложение запускается через `docker-compose up` без ошибок
- [ ] Backend доступен на `http://localhost:8000/docs` (Swagger UI)
- [ ] Frontend доступен на `http://localhost:3000`
- [ ] Frontend корректно проксирует API-запросы к backend через nginx
- [ ] SQLite-файл персистентен при перезапуске (Docker volume)

### Качество интерфейса

- [ ] Все 6 страниц отображаются корректно в Chrome 100+
- [ ] Нет `console.error` в браузере при стандартном использовании
- [ ] Дашборд читаем на экране 1280x720 (минимальное разрешение)
- [ ] Язык интерфейса -- русский
- [ ] Loading spinner отображается при загрузке данных
- [ ] При ошибках API показывается понятное сообщение пользователю

### Данные

- [ ] CSV данные загружены корректно (>= 126K записей за январь 2023)
- [ ] Общее количество `queue_records` >= 1,500,000 (14 месяцев)
- [ ] `SELECT COUNT(DISTINCT branch_id) FROM queue_records` >= 44
- [ ] `hourly_stats` содержит ~153,000 записей (44 филиала x ~290 дней x 12 часов)
- [ ] Нет пустых строк вместо NULL в БД
- [ ] `wait_duration` и `service_duration` хранятся в секундах (INTEGER)
