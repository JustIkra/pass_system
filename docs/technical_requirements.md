# Technical Requirements: Система прогнозирования загрузки окон МФЦ

**Версия:** 1.0
**Дата:** 2026-02-09
**Статус:** Draft
**Связанный документ:** [Product Vision](product_vision.md)

---

## Обзор источников данных

Данные АИС поступают в виде CSV-файлов (разделитель `;`, кодировка UTF-8) за период январь 2023 -- февраль 2024 (14 месяцев). Всего ~1.7 GB.

### Типы файлов

| Тип файла | Пример заголовков | Периодичность | Кол-во файлов |
|-----------|-------------------|---------------|---------------|
| **Статистика ЭО** | `Branch_ID;Branch_name;Customer_number_Queue;Employee_window;Employee_ID;Data_zapis;Time_zapis;Data_vizov;Time_vizov;Time_wait_vizov;Customer_result_ID;Customer_result;Employee_func_ID;Employee_func;Provided_service_ID;Provided_service;Data_end;Time_end;Time_priem;ID_dossier;Pre_registration` | Помесячно | 14 |
| **Журнал ролей** | `Employee_ID;Branch_ID;Date_begin;Time_begin;Date_end;Time_end;Role_ID;Role_Name` | Помесячно | 14 |
| **Справочник специалистов** | `Employee_ID;FIO;Tab_num;Branch;Post;Nast_Employee_ID` | Помесячно | 14 |
| **Справочник услуг** | `Provided_service_ID;Provided_service;Provided_service_s;Service_ID;Service_name;Service_name_f` | Помесячно | 14 |
| **Справочник филиалов** | `Depart_name_mfc;Depart_id;Branch` | Единоразово | 1 |
| **Нормативы услуг** | `id;provided_service_s;provided_service_f;provided_service_normativ` | Единоразово | 2 |
| **Группы услуг по специалистам** | `Employee_ID;Provided_service_ID` | Единоразово | 1 |
| **Этапы по принятым делам** | (дополнительные) | Помесячно | 14 |

---

## Блок 1: Backend -- ETL и данные

### Задача 1.1: Структура проекта

**Описание:** Создать скелет проекта с разделением на backend, frontend, data, scripts и docs.

**Структура папок:**

```
pass_system/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application entry point
│   │   ├── config.py            # Settings (DB path, model dir, CSV dir)
│   │   ├── database.py          # SQLAlchemy engine, session, Base
│   │   ├── models/              # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── branch.py
│   │   │   ├── employee.py
│   │   │   ├── service.py
│   │   │   ├── queue_record.py
│   │   │   ├── employee_role.py
│   │   │   ├── forecast.py
│   │   │   └── hourly_stats.py
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── branch.py
│   │   │   ├── forecast.py
│   │   │   ├── analytics.py
│   │   │   └── staffing.py
│   │   ├── api/                 # FastAPI routers
│   │   │   ├── __init__.py
│   │   │   ├── branches.py
│   │   │   ├── forecast.py
│   │   │   ├── analytics.py
│   │   │   └── data.py
│   │   ├── services/            # Business logic layer
│   │   │   ├── __init__.py
│   │   │   ├── etl.py           # CSV parsing, data cleaning, DB loading
│   │   │   ├── forecast.py      # Forecast generation from trained models
│   │   │   ├── analytics.py     # Aggregation, comparison, overview
│   │   │   └── staffing.py      # Staffing recommendations
│   │   └── ml/                  # ML training and inference
│   │       ├── __init__.py
│   │       ├── features.py      # Feature engineering
│   │       ├── train.py         # Model training pipeline
│   │       ├── predict.py       # Model inference
│   │       └── evaluate.py      # Backtesting and evaluation
│   ├── tests/
│   │   ├── test_etl.py
│   │   ├── test_api.py
│   │   └── test_ml.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/          # Reusable UI components
│   │   │   ├── Layout.tsx
│   │   │   ├── BranchSelector.tsx
│   │   │   ├── MonthPicker.tsx
│   │   │   ├── HeatmapChart.tsx
│   │   │   ├── LineChart.tsx
│   │   │   ├── LoadIndicator.tsx
│   │   │   └── StaffingTable.tsx
│   │   ├── pages/               # Page-level components
│   │   │   ├── Overview.tsx
│   │   │   ├── BranchDetail.tsx
│   │   │   ├── Windows.tsx
│   │   │   ├── Staffing.tsx
│   │   │   ├── Compare.tsx
│   │   │   └── History.tsx
│   │   ├── api/                 # API client functions
│   │   │   └── client.ts
│   │   ├── types/               # TypeScript interfaces
│   │   │   └── index.ts
│   │   ├── hooks/               # Custom React hooks
│   │   │   └── useApi.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── Dockerfile
├── scripts/
│   ├── init_db.py               # Create tables + load all CSV
│   ├── train_model.py           # Train Prophet models
│   └── generate_forecast.py     # Generate forecasts from trained models
├── models/                      # Trained model files (.pkl)
├── data/                        # Symlink to CSV data or copy
├── docker-compose.yml
└── docs/
    ├── product_vision.md
    └── technical_requirements.md
```

**Входные данные:** Нет (начальная настройка).

**Выходной артефакт:** Файловая структура проекта со всеми `__init__.py`, пустыми модулями и заглушками.

**Критерии приемки (DoD):**
- [ ] Все папки и файлы созданы
- [ ] `backend/app/main.py` содержит минимальный запускаемый FastAPI-app с healthcheck (`GET /health` -> 200)
- [ ] `frontend/` содержит инициализированный Vite + React + TypeScript проект (`npm run dev` запускается без ошибок)
- [ ] `docker-compose.yml` описывает сервисы backend, frontend (заглушки)
- [ ] Проект запускается через `docker-compose up` без ошибок

---

### Задача 1.2: Загрузка и парсинг CSV

**Описание:** Реализовать ETL-пайплайн для парсинга всех CSV-файлов из `Исходные данные АИС/` и загрузки данных в БД.

**Источники CSV и маппинг колонок:**

#### 1. Статистика ЭО (queue_records)

| CSV-колонка | Тип в CSV | Преобразование | Поле в БД |
|-------------|-----------|----------------|-----------|
| `Branch_ID` | int | as-is | `branch_id` |
| `Branch_name` | str | справочно (не хранить отдельно) | -- |
| `Customer_number_Queue` | str | as-is (напр. "А1", "В1") | `customer_number` |
| `Employee_window` | int/null | nullable int | `employee_window` |
| `Employee_ID` | int/null | nullable int FK | `employee_id` |
| `Data_zapis` | str "DD.MM.YYYY" | parse -> date | `registered_at` (date part) |
| `Time_zapis` | str "HH:MM:SS" | parse -> time | `registered_at` (time part) |
| `Data_vizov` | str/null | parse -> date or null | `called_at` (date part) |
| `Time_vizov` | str/null | parse -> time or null | `called_at` (time part) |
| `Time_wait_vizov` | str "HH:MM:SS"/null | parse -> timedelta | `wait_duration` |
| `Customer_result_ID` | int | as-is | `result_id` |
| `Customer_result` | str | as-is | `result_name` |
| `Employee_func_ID` | int | as-is | `func_id` |
| `Employee_func` | str | as-is | `func_name` |
| `Provided_service_ID` | int | as-is | `service_id` |
| `Provided_service` | str | as-is | `service_name` |
| `Data_end` | str/null | parse -> date or null | `ended_at` (date part) |
| `Time_end` | str/null | parse -> time or null | `ended_at` (time part) |
| `Time_priem` | str/null "HH:MM:SS" | parse -> timedelta | `service_duration` |
| `ID_dossier` | int/null | nullable int | `dossier_id` |
| `Pre_registration` | int 0/1 | bool | `pre_registration` |

**Комбинация дата+время:** `registered_at = datetime(Data_zapis + Time_zapis)`, аналогично для `called_at` и `ended_at`.

#### 2. Журнал ролей (employee_roles)

| CSV-колонка | Преобразование | Поле в БД |
|-------------|----------------|-----------|
| `Employee_ID` | FK | `employee_id` |
| `Branch_ID` | FK | `branch_id` |
| `Date_begin` + `Time_begin` | datetime | `started_at` |
| `Date_end` + `Time_end` | datetime | `ended_at` |
| `Role_ID` | int | `role_id` |
| `Role_Name` | str | `role_name` |

#### 3. Справочник специалистов (employees)

| CSV-колонка | Преобразование | Поле в БД |
|-------------|----------------|-----------|
| `Employee_ID` | PK | `id` |
| `FIO` | str | `fio` |
| `Tab_num` | str | `tab_num` |
| `Branch` | FK | `branch_id` |
| `Post` | str | `post` |
| `Nast_Employee_ID` | nullable int (игнорируем в MVP) | -- |

**Особенность:** Справочник специалистов помесячный -- один сотрудник может появиться в нескольких файлах. При загрузке используется UPSERT по `Employee_ID`: берется последняя (самая свежая) запись.

#### 4. Справочник филиалов (branches)

| CSV-колонка | Преобразование | Поле в БД |
|-------------|----------------|-----------|
| `Depart_name_mfc` | str | `depart_name_mfc` |
| `Depart_id` | str "NULL" -> null | `depart_id` |
| `Branch` | PK | `id` |

**Особенность:** Поле `name` в таблице `branches` заполняется из `Branch_name` в Статистике ЭО (маппинг `Branch_ID` -> первое встретившееся `Branch_name`).

#### 5. Нормативы длительности услуг (services)

| CSV-колонка | Преобразование | Поле в БД |
|-------------|----------------|-----------|
| `id` | PK | `id` |
| `provided_service_s` | str | `name_short` |
| `provided_service_f` | str | `name` |
| `provided_service_normativ` | int (минуты) | `normativ_minutes` |

#### 6. Группы услуг по специалистам

Таблица связи `Employee_ID` <-> `Provided_service_ID`. В MVP используется только для обогащения рекомендаций по штату. Загружается в отдельную таблицу `employee_services` (many-to-many).

**Правила обработки данных:**
1. **Разделитель:** точка с запятой (`;`)
2. **Кавычки:** некоторые файлы используют двойные кавычки вокруг значений (справочники), другие -- нет (статистика). Парсер должен обрабатывать оба случая.
3. **Даты:** формат `DD.MM.YYYY`, парсить через `datetime.strptime(val, "%d.%m.%Y")`
4. **Время:** формат `HH:MM:SS`, парсить через `datetime.strptime(val, "%H:%M:%S").time()`
5. **Пустые значения:** пустая строка или отсутствие значения -> `NULL` в БД
6. **Строка "NULL":** в справочнике филиалов `Depart_id` содержит строку `"NULL"` -> интерпретировать как `NULL`
7. **Дубликаты:** в `queue_records` дубликатов не ожидается (каждая строка -- уникальная операция). В справочниках -- UPSERT.
8. **Порядок загрузки:** branches -> services -> employees -> queue_records -> employee_roles -> employee_services

**Файлы для загрузки (полный перечень):**
- 14 файлов "Статистика ЭО для WMF" (2023-01 .. 2024-02)
- 14 файлов "Журнал ролей специалистов" (2023-01 .. 2024-02)
- 14 файлов "Справочник специалистов" (2023-01 .. 2024-02)
- 1 файл "Справочник филиалов"
- 1 файл "Нормативы длительности услуг (только заполненные)"
- 1 файл "Группы услуг по специалистам"

Итого: **44 файла** основных + 14 файлов "Справочник услуг и групп услуг" (опциональные, для обогащения).

**Входные данные:** CSV-файлы из `Исходные данные АИС/_2023/` и `_2024/`.

**Выходной артефакт:**
- Модуль `backend/app/services/etl.py` с функциями: `parse_queue_csv()`, `parse_roles_csv()`, `parse_employees_csv()`, `parse_branches_csv()`, `parse_services_csv()`, `load_all()`
- Скрипт `scripts/init_db.py`
- Логирование: количество записей загружено, количество ошибок, время выполнения

**Критерии приемки (DoD):**
- [ ] Все 44 основных CSV-файла парсятся без ошибок
- [ ] Даты и время корректно преобразованы в datetime-объекты
- [ ] Пустые значения корректно обработаны (NULL в БД, не пустые строки)
- [ ] Строка "NULL" в справочнике филиалов обработана как NULL
- [ ] Дубликаты специалистов разрешены через UPSERT (последняя запись)
- [ ] `scripts/init_db.py` выполняется за < 10 минут на всех данных
- [ ] После загрузки: `SELECT COUNT(*) FROM queue_records` возвращает ~1 500 000+ записей (14 месяцев x ~126 000/месяц, с учетом неполного февраля 2024)
- [ ] После загрузки: `SELECT COUNT(DISTINCT branch_id) FROM queue_records` >= 44
- [ ] Лог загрузки выводит итоговую статистику: кол-во записей по таблицам, кол-во пропущенных/ошибочных строк

---

### Задача 1.3: Схема БД

**Описание:** Создать SQLAlchemy-модели для всех таблиц. СУБД: SQLite для MVP (с возможностью перехода на PostgreSQL через изменение `DATABASE_URL` в конфиге).

**Таблицы:**

```sql
-- Филиалы
CREATE TABLE branches (
    id              INTEGER PRIMARY KEY,       -- Branch_ID из CSV
    name            TEXT,                       -- Branch_name (из Статистики ЭО)
    depart_name_mfc TEXT,                       -- Из справочника филиалов
    depart_id       INTEGER                     -- Из справочника филиалов (nullable)
);

-- Сотрудники
CREATE TABLE employees (
    id         INTEGER PRIMARY KEY,             -- Employee_ID из CSV
    fio        TEXT NOT NULL,
    tab_num    TEXT,
    branch_id  INTEGER REFERENCES branches(id),
    post       TEXT
);

-- Услуги (с нормативами)
CREATE TABLE services (
    id               INTEGER PRIMARY KEY,       -- Provided_service_ID / id из нормативов
    name             TEXT NOT NULL,              -- provided_service_f
    name_short       TEXT,                       -- provided_service_s
    normativ_minutes INTEGER                     -- Норматив в минутах (nullable)
);

-- Записи электронной очереди (основная таблица фактов)
CREATE TABLE queue_records (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id        INTEGER NOT NULL REFERENCES branches(id),
    customer_number  TEXT,                       -- "А1", "В1", etc.
    employee_window  INTEGER,                    -- Номер окна (nullable)
    employee_id      INTEGER REFERENCES employees(id),
    registered_at    TIMESTAMP NOT NULL,         -- Дата+время записи в очередь
    called_at        TIMESTAMP,                  -- Дата+время вызова (nullable)
    wait_duration    INTEGER,                    -- Время ожидания в секундах (nullable)
    result_id        INTEGER NOT NULL,           -- 1=принят, 2=неявка, 3=удален, etc.
    result_name      TEXT NOT NULL,
    func_id          INTEGER,
    func_name        TEXT,
    service_id       INTEGER REFERENCES services(id),
    service_name     TEXT,
    ended_at         TIMESTAMP,                  -- Дата+время окончания (nullable)
    service_duration INTEGER,                    -- Длительность обслуживания в секундах (nullable)
    dossier_id       INTEGER,
    pre_registration BOOLEAN DEFAULT FALSE
);

-- Журнал ролей специалистов
CREATE TABLE employee_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    branch_id   INTEGER NOT NULL REFERENCES branches(id),
    started_at  TIMESTAMP NOT NULL,
    ended_at    TIMESTAMP NOT NULL,
    role_id     INTEGER NOT NULL,
    role_name   TEXT NOT NULL
);

-- Связь специалист <-> услуга (many-to-many)
CREATE TABLE employee_services (
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    service_id  INTEGER NOT NULL REFERENCES services(id),
    PRIMARY KEY (employee_id, service_id)
);

-- Прогнозы (генерируемые ML-моделью)
CREATE TABLE forecasts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id           INTEGER NOT NULL REFERENCES branches(id),
    date                DATE NOT NULL,
    hour                INTEGER NOT NULL CHECK (hour >= 0 AND hour <= 23),
    predicted_visits    REAL NOT NULL,
    predicted_avg_wait  REAL,                    -- Прогноз ср. ожидания (минуты)
    predicted_avg_service REAL,                  -- Прогноз ср. обслуживания (минуты)
    confidence_lower    REAL,                    -- Нижняя граница доверительного интервала
    confidence_upper    REAL,                    -- Верхняя граница
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Агрегированная почасовая статистика (для быстрых запросов и ML)
CREATE TABLE hourly_stats (
    branch_id            INTEGER NOT NULL REFERENCES branches(id),
    date                 DATE NOT NULL,
    hour                 INTEGER NOT NULL CHECK (hour >= 0 AND hour <= 23),
    total_visits         INTEGER NOT NULL DEFAULT 0,
    served_visits        INTEGER NOT NULL DEFAULT 0,  -- result_id = 1 (принят)
    cancelled_visits     INTEGER NOT NULL DEFAULT 0,  -- result_id != 1
    avg_wait_minutes     REAL,
    avg_service_minutes  REAL,
    max_wait_minutes     REAL,
    num_windows_active   INTEGER DEFAULT 0,
    num_employees_active INTEGER DEFAULT 0,
    PRIMARY KEY (branch_id, date, hour)
);
```

**Индексы:**

```sql
-- Быстрый поиск записей по филиалу и дате
CREATE INDEX idx_queue_records_branch_date ON queue_records (branch_id, registered_at);

-- Быстрый поиск по result_id (фильтрация принятых)
CREATE INDEX idx_queue_records_result ON queue_records (result_id);

-- Индексы для прогнозов
CREATE INDEX idx_forecasts_branch_date ON forecasts (branch_id, date, hour);

-- hourly_stats уже имеет составной PK (branch_id, date, hour)

-- Индекс для ролей
CREATE INDEX idx_employee_roles_branch_date ON employee_roles (branch_id, started_at);
```

**Входные данные:** Спецификация таблиц выше.

**Выходной артефакт:**
- Модули в `backend/app/models/` -- по одному файлу на модель
- `backend/app/database.py` -- engine, sessionmaker, Base
- Миграция (Alembic init или `Base.metadata.create_all()` для MVP)

**Критерии приемки (DoD):**
- [ ] Все таблицы создаются через `Base.metadata.create_all()` без ошибок
- [ ] Все FK-ограничения работают (попытка вставить queue_record с несуществующим branch_id вызывает ошибку)
- [ ] Индексы создаются и используются (проверить через `EXPLAIN QUERY PLAN`)
- [ ] `hourly_stats` имеет составной PK и не допускает дубликатов `(branch_id, date, hour)`
- [ ] `wait_duration` и `service_duration` хранятся в секундах (INTEGER), а не как строки
- [ ] SQLAlchemy-модели имеют корректные relationships (Branch.queue_records, Employee.roles, etc.)

---

### Задача 1.4: REST API

**Описание:** Реализовать FastAPI-эндпоинты для взаимодействия с фронтендом.

**Base URL:** `/api`

#### Endpoints:

##### 1. `GET /api/branches`
**Описание:** Список всех филиалов.

**Response 200:**
```json
[
  {
    "id": 176,
    "name": "Филиал Конышевский район",
    "depart_name_mfc": "Филиал АУ КО МФЦ по Конышевскому району",
    "total_records": 3456,
    "date_range": {"from": "2023-01-01", "to": "2024-02-21"}
  }
]
```

##### 2. `GET /api/branches/{id}`
**Описание:** Детальная информация о филиале.

**Response 200:**
```json
{
  "id": 176,
  "name": "Филиал Конышевский район",
  "depart_name_mfc": "Филиал АУ КО МФЦ по Конышевскому району",
  "total_records": 3456,
  "num_employees": 12,
  "num_windows": 8,
  "avg_daily_visits": 28.5,
  "avg_wait_minutes": 12.3,
  "avg_service_minutes": 15.7,
  "top_services": [
    {"service_id": 3, "service_name": "Отдел по вопросам миграции УМВД", "count": 1200}
  ]
}
```

**Response 404:** `{"detail": "Branch not found"}`

##### 3. `GET /api/branches/{id}/forecast?month=2026-03`
**Описание:** Прогноз загрузки филиала на указанный месяц. Возвращает почасовые данные.

**Query params:**
- `month` (required): формат `YYYY-MM`

**Response 200:**
```json
{
  "branch_id": 176,
  "branch_name": "Филиал Конышевский район",
  "month": "2026-03",
  "data": [
    {
      "date": "2026-03-02",
      "hour": 9,
      "predicted_visits": 12.5,
      "predicted_avg_wait": 8.3,
      "confidence_lower": 8.0,
      "confidence_upper": 17.0
    }
  ],
  "summary": {
    "total_predicted_visits": 3200,
    "peak_day": "2026-03-15",
    "peak_hour": 11,
    "avg_daily_visits": 103.2
  }
}
```

##### 4. `GET /api/branches/{id}/windows?month=2026-03`
**Описание:** Прогноз загрузки по окнам филиала (на основе исторического распределения).

**Response 200:**
```json
{
  "branch_id": 176,
  "month": "2026-03",
  "windows": [
    {
      "window_number": 1,
      "avg_daily_load_percent": 78.5,
      "load_by_hour": [
        {"hour": 9, "load_percent": 65.0, "avg_visits": 5.2}
      ],
      "status": "normal"
    }
  ]
}
```

**Цветовая индикация `status`:**
- `"overloaded"` -- загрузка > 85%
- `"normal"` -- загрузка 50-85%
- `"underloaded"` -- загрузка 20-50%
- `"idle"` -- загрузка < 20%

Расчет загрузки: `load_percent = (actual_service_minutes / (60 * normativ_coefficient)) * 100`, где `normativ_coefficient` учитывает средний норматив услуги.

##### 5. `GET /api/branches/{id}/staffing?month=2026-03`
**Описание:** Рекомендации по количеству сотрудников.

**Response 200:**
```json
{
  "branch_id": 176,
  "month": "2026-03",
  "recommendations": [
    {
      "date": "2026-03-02",
      "hour": 9,
      "predicted_visits": 12.5,
      "avg_service_minutes": 15.0,
      "required_windows": 4,
      "current_windows_avg": 3,
      "delta": 1,
      "status": "understaffed"
    }
  ]
}
```

**Формула расчета:**
```
required_windows = ceil(predicted_visits * avg_service_minutes / 60)
```
Если `avg_service_minutes` недоступен, используется средний норматив из таблицы `services`.

##### 6. `GET /api/branches/{id}/history?from=2023-01&to=2024-02`
**Описание:** Исторические агрегированные данные (из `hourly_stats`).

**Query params:**
- `from` (required): формат `YYYY-MM`
- `to` (required): формат `YYYY-MM`

**Response 200:**
```json
{
  "branch_id": 176,
  "period": {"from": "2023-01", "to": "2024-02"},
  "daily": [
    {
      "date": "2023-01-03",
      "total_visits": 45,
      "avg_wait_minutes": 10.2,
      "avg_service_minutes": 14.8,
      "peak_hour": 11
    }
  ],
  "hourly": [
    {
      "date": "2023-01-03",
      "hour": 9,
      "total_visits": 8,
      "avg_wait_minutes": 5.1,
      "avg_service_minutes": 12.3,
      "num_windows_active": 4
    }
  ]
}
```

##### 7. `GET /api/branches/compare?ids=1,2,3&month=2026-03`
**Описание:** Сравнение нескольких филиалов (2-5).

**Query params:**
- `ids` (required): список ID через запятую (2-5 значений)
- `month` (required): формат `YYYY-MM`

**Response 200:**
```json
{
  "month": "2026-03",
  "branches": [
    {
      "id": 1,
      "name": "Филиал 1",
      "predicted_total_visits": 3200,
      "predicted_avg_wait": 12.3,
      "predicted_avg_service": 15.1,
      "predicted_peak_hour": 11,
      "required_avg_windows": 5,
      "overloaded_hours_count": 8
    }
  ]
}
```

**Response 400:** `{"detail": "Provide 2-5 branch IDs"}` (если передано <2 или >5 ID)

##### 8. `GET /api/analytics/overview?month=2026-03`
**Описание:** Общая сводка по всей сети.

**Response 200:**
```json
{
  "month": "2026-03",
  "total_branches": 44,
  "total_predicted_visits": 126000,
  "avg_predicted_wait": 11.5,
  "top_overloaded": [
    {"branch_id": 1, "branch_name": "Филиал 1", "predicted_avg_wait": 25.3, "overloaded_hours": 15}
  ],
  "top_underloaded": [
    {"branch_id": 10, "branch_name": "Филиал 10", "predicted_avg_wait": 3.1, "avg_load_percent": 22.0}
  ]
}
```

##### 9. `POST /api/data/upload`
**Описание:** Загрузка нового CSV-файла (multipart/form-data).

**Request:** `multipart/form-data` с полем `file` (CSV) и `type` (string: `"queue"`, `"roles"`, `"employees"`).

**Response 200:**
```json
{
  "status": "ok",
  "records_loaded": 125000,
  "records_skipped": 12,
  "duration_seconds": 45.2
}
```

**Response 400:** `{"detail": "Invalid CSV format"}` (если колонки не совпадают с ожидаемыми)

##### 10. `POST /api/model/retrain`
**Описание:** Запуск переобучения ML-моделей (асинхронно).

**Response 202:**
```json
{
  "status": "training_started",
  "message": "Model retraining initiated for 44 branches. Check /api/model/status for progress."
}
```

##### 11. `GET /api/model/status`
**Описание:** Статус обучения модели.

**Response 200:**
```json
{
  "status": "training",
  "progress": 23,
  "total_branches": 44,
  "current_branch": "Филиал Конышевский район",
  "started_at": "2026-02-09T14:30:00"
}
```

**CORS:** Разрешить `http://localhost:5173` (Vite dev server) и `http://localhost:3000`.

**Входные данные:** Загруженная БД, обученные модели.

**Выходной артефакт:**
- Модули в `backend/app/api/` -- по роутеру на группу endpoints
- Модули в `backend/app/schemas/` -- Pydantic-схемы
- Модули в `backend/app/services/` -- бизнес-логика

**Критерии приемки (DoD):**
- [ ] Все 11 endpoints возвращают корректные HTTP-коды (200, 202, 400, 404)
- [ ] Response body соответствует описанным JSON-схемам
- [ ] `GET /api/branches` возвращает >= 44 филиала
- [ ] `GET /api/branches/{id}/forecast` возвращает данные за каждый рабочий час запрошенного месяца
- [ ] Query-параметры валидируются (неверный формат month -> 422)
- [ ] `POST /api/data/upload` обрабатывает CSV с разделителем `;`
- [ ] Время ответа для любого GET-запроса < 2 секунды
- [ ] Swagger UI доступен по `/docs`
- [ ] Автотесты в `tests/test_api.py` покрывают все endpoints (минимум happy path)

---

## Блок 2: ML -- Модель прогнозирования

### Задача 2.1: Подготовка данных для ML

**Описание:** Агрегировать `queue_records` в `hourly_stats` и подготовить feature-набор для обучения Prophet.

**Агрегация queue_records -> hourly_stats:**

Для каждой уникальной комбинации `(branch_id, date, hour)`:

```python
total_visits = COUNT(*)                            # все обращения
served_visits = COUNT(*) WHERE result_id = 1       # принятые специалистом
cancelled_visits = total_visits - served_visits
avg_wait_minutes = AVG(wait_duration) / 60         # только для ненулевых
avg_service_minutes = AVG(service_duration) / 60   # только для ненулевых
max_wait_minutes = MAX(wait_duration) / 60
num_windows_active = COUNT(DISTINCT employee_window) WHERE employee_window IS NOT NULL
num_employees_active = COUNT(DISTINCT employee_id) WHERE employee_id IS NOT NULL
```

**Где `hour`** = час из `registered_at` (EXTRACT HOUR).

**Обработка пропущенных часов:**
- Рабочие часы МФЦ: 08:00-20:00 (varies by branch, но для MVP считаем единым)
- Для каждого `(branch_id, date)` заполнить все часы 8-19 (12 часов)
- Если в час нет записей -> `total_visits=0, served_visits=0, avg_wait=NULL, ...`
- Нерабочие дни (воскресенье, праздники) -- не заполнять нулями, пропускать

**Feature engineering (для Prophet):**

Prophet использует формат `ds` (datetime) + `y` (target). Дополнительные регрессоры:

| Feature | Тип | Описание |
|---------|-----|----------|
| `ds` | datetime | `date + hour:00:00` |
| `y` | float | `total_visits` |
| `day_of_week` | int 0-6 | Понедельник=0, Воскресенье=6 |
| `month` | int 1-12 | Месяц |
| `is_holiday` | bool | Государственный праздник РФ |
| `is_month_start` | bool | Первые 3 рабочих дня месяца (повышенная нагрузка) |
| `is_month_end` | bool | Последние 3 рабочих дня месяца |
| `is_monday` | bool | Понедельник (часто пик) |

**Список праздников РФ (для is_holiday):**
- 1-8 января (новогодние каникулы)
- 23 февраля (День защитника Отечества)
- 8 марта (Международный женский день)
- 1 мая (Праздник Весны и Труда)
- 9 мая (День Победы)
- 12 июня (День России)
- 4 ноября (День народного единства)

**Входные данные:** Таблица `queue_records` (1.5M+ записей), таблица `employee_roles`.

**Выходной артефакт:**
- Заполненная таблица `hourly_stats` в БД
- Модуль `backend/app/ml/features.py` с функцией `prepare_prophet_data(branch_id) -> DataFrame`
- Feature-набор: DataFrame с колонками `[ds, y, day_of_week, month, is_holiday, is_month_start, is_month_end, is_monday]`

**Критерии приемки (DoD):**
- [ ] `hourly_stats` содержит записи для всех 44 филиалов
- [ ] Для каждого `(branch_id, date)` присутствуют записи для часов 8-19 (включая нулевые)
- [ ] Нет записей для нерабочих дней (воскресенья, праздники)
- [ ] `avg_wait_minutes` и `avg_service_minutes` корректны (выборочная проверка 5 записей вручную)
- [ ] Feature `is_holiday` корректно размечен для 2023-2024 годов
- [ ] `prepare_prophet_data(branch_id)` возвращает DataFrame без NaN в колонке `y`
- [ ] Количество строк в hourly_stats: ~44 филиала x ~290 рабочих дней x 12 часов ~ 153 000

---

### Задача 2.2: Обучение модели

**Описание:** Обучить модели Prophet для прогнозирования `total_visits` по каждому филиалу.

**Архитектура моделей:**
- **Отдельная модель для каждого филиала** (44 модели)
- Библиотека: `prophet` (Facebook Prophet)
- Целевая переменная: `total_visits` (количество обращений за час)

**Конфигурация Prophet:**

```python
from prophet import Prophet

model = Prophet(
    yearly_seasonality=True,     # Годовая сезонность
    weekly_seasonality=True,     # Недельная сезонность
    daily_seasonality=False,     # Не используем (данные уже почасовые)
    changepoint_prior_scale=0.05,
    seasonality_prior_scale=10.0,
    holidays_prior_scale=10.0,
    interval_width=0.80          # 80% доверительный интервал
)

# Добавить кастомную суточную сезонность
model.add_seasonality(
    name='intraday',
    period=1,                    # 1 день
    fourier_order=8              # Гибкость суточного паттерна
)

# Добавить праздники РФ
model.add_country_holidays(country_name='RU')

# Добавить регрессоры
model.add_regressor('is_month_start')
model.add_regressor('is_month_end')
model.add_regressor('is_monday')
```

**Процесс обучения:**

1. Для каждого `branch_id`:
   a. Получить `prepare_prophet_data(branch_id)` -> DataFrame
   b. Проверить: если < 100 точек данных -> пропустить (логировать warning)
   c. Обучить модель: `model.fit(df)`
   d. Сохранить модель: `joblib.dump(model, f"models/prophet_branch_{branch_id}.pkl")`
   e. Записать метрики обучения в лог

2. Сохранить метаданные обучения:
   ```json
   {
     "trained_at": "2026-02-09T15:00:00",
     "num_branches": 44,
     "train_period": {"from": "2023-01-01", "to": "2024-02-21"},
     "branches_skipped": [],
     "avg_training_time_seconds": 12.5
   }
   ```

**Метрики качества (вычисляются на training data как baseline):**

| Метрика | Целевое значение | Формула |
|---------|------------------|---------|
| MAPE | < 20% на уровне день/филиал | `mean(abs(y - yhat) / y) * 100` (только для y > 0) |
| MAE (visits) | < 3 визита/час | `mean(abs(y - yhat))` |
| RMSE | < 5 визитов/час | `sqrt(mean((y - yhat)^2))` |

**Входные данные:** Feature-набор из задачи 2.1. Таблица `hourly_stats`.

**Выходной артефакт:**
- 44 файла моделей в `models/prophet_branch_{id}.pkl`
- Файл метаданных `models/training_metadata.json`
- Скрипт `scripts/train_model.py`
- Модуль `backend/app/ml/train.py`

**Критерии приемки (DoD):**
- [ ] Обучены модели для >= 40 филиалов (допускается пропуск филиалов с < 100 точек данных)
- [ ] Каждая модель сохранена в `models/` и загружается без ошибок
- [ ] MAPE < 20% для >= 80% филиалов (на training data)
- [ ] Скрипт `scripts/train_model.py` выполняется за < 30 минут
- [ ] Логи обучения выводят прогресс (X/44 branches) и метрики по каждому филиалу
- [ ] `training_metadata.json` содержит корректные метаданные

---

### Задача 2.3: Валидация (backtesting)

**Описание:** Провести backtesting для оценки реальной прогнозной способности моделей.

**Схема разбиения:**

```
|--- Training ---|--- Test ---|
2023-01 ... 2023-09  2023-10 ... 2024-02
    (9 месяцев)        (5 месяцев)
```

**Процесс:**
1. Для каждого `branch_id`:
   a. Разделить данные: train = данные до 2023-09-30, test = данные с 2023-10-01
   b. Обучить Prophet на train
   c. Сгенерировать прогноз на период test
   d. Сравнить с фактом

**Метрики валидации (по каждому филиалу):**

| Метрика | Уровень | Целевое значение |
|---------|---------|------------------|
| MAPE | день (sum by hours) | < 20% |
| MAE wait_time | час | < 5 минут |
| Peak accuracy | неделя (top-3 часа) | > 70% совпадений |
| Coverage | час (80% CI) | > 75% фактических значений попадают в интервал |

**Peak accuracy** = доля недель, в которых 2 из 3 самых загруженных часов совпадают между прогнозом и фактом.

**Отчет валидации:**

```
=== Backtesting Report ===
Branch: Филиал Конышевский район (ID=176)
Train period: 2023-01-01 to 2023-09-30
Test period:  2023-10-01 to 2024-02-21
Total test points: 1800

MAPE (daily):     15.3%   [OK]
MAE (wait, min):  3.8     [OK]
Peak accuracy:    72%     [OK]
CI coverage:      81%     [OK]

Overall: 38/44 branches meet all criteria
```

**Визуализации:**
- Линейный график: факт vs прогноз (дневная агрегация) для каждого филиала
- Scatter plot: predicted vs actual (по часам) с линией идеального прогноза
- Distribution plot: распределение ошибок (гистограмма MAPE по филиалам)

**Входные данные:** Данные `hourly_stats` за весь период.

**Выходной артефакт:**
- Модуль `backend/app/ml/evaluate.py` с функциями `backtest(branch_id)`, `generate_report()`
- Отчет в `models/backtesting_report.json`:
  ```json
  {
    "branches": [
      {
        "branch_id": 176,
        "branch_name": "Филиал Конышевский район",
        "mape_daily": 15.3,
        "mae_wait": 3.8,
        "peak_accuracy": 0.72,
        "ci_coverage": 0.81,
        "passed": true
      }
    ],
    "summary": {
      "branches_passed": 38,
      "branches_total": 44,
      "avg_mape": 16.2,
      "avg_mae_wait": 4.1
    }
  }
  ```
- Графики в `models/plots/` (PNG)

**Критерии приемки (DoD):**
- [ ] Backtesting выполнен для всех 44 филиалов
- [ ] MAPE < 20% для >= 80% филиалов (на test data)
- [ ] MAE wait_time < 5 минут для >= 80% филиалов
- [ ] `backtesting_report.json` содержит метрики по каждому филиалу
- [ ] Графики факт vs прогноз сгенерированы минимум для 5 филиалов
- [ ] Отчет доступен через API: `GET /api/model/quality`

---

### Задача 2.4: Inference API

**Описание:** Организовать загрузку обученных моделей и генерацию прогнозов по запросу.

**Процесс inference:**

1. **При старте приложения:**
   - Загрузить все модели из `models/prophet_branch_{id}.pkl` в память
   - Хранить в словаре: `{branch_id: model}`
   - Логировать количество загруженных моделей

2. **При запросе прогноза (`GET /api/branches/{id}/forecast?month=YYYY-MM`):**
   a. Проверить, что модель для `branch_id` загружена. Если нет -> 404.
   b. Создать future DataFrame:
      ```python
      # Все рабочие дни запрошенного месяца, часы 8-19
      future = create_future_dataframe(month, branch_id)
      # Добавить регрессоры: is_month_start, is_month_end, is_monday
      future = add_features(future)
      ```
   c. Вызвать `model.predict(future)` -> получить `yhat`, `yhat_lower`, `yhat_upper`
   d. Post-processing:
      - `predicted_visits = max(0, round(yhat, 1))` -- не допускать отрицательных
      - `confidence_lower = max(0, round(yhat_lower, 1))`
      - `confidence_upper = max(0, round(yhat_upper, 1))`
   e. Вернуть результат

3. **Кэширование:**
   - Кэшировать результаты прогноза в таблицу `forecasts`
   - При повторном запросе того же `(branch_id, month)` -- вернуть из кэша
   - Кэш инвалидируется при переобучении модели (`POST /api/model/retrain`)

4. **Прогноз среднего времени ожидания:**
   - Рассчитывается по формуле на основе predicted_visits, исторического avg_service_minutes и текущего кол-ва окон:
     ```
     predicted_avg_wait = (predicted_visits * avg_service_per_visit) / num_windows - avg_service_per_visit
     ```
   - Ограничение: `max(0, predicted_avg_wait)`

**Входные данные:** Обученные модели (pkl), запрос с `branch_id` и `month`.

**Выходной артефакт:**
- Модуль `backend/app/ml/predict.py` с классом `ForecastEngine`:
  ```python
  class ForecastEngine:
      def __init__(self, model_dir: str):
          self.models: dict[int, Prophet] = {}
          self.load_models()

      def load_models(self) -> None: ...
      def predict(self, branch_id: int, month: str) -> list[ForecastPoint]: ...
      def invalidate_cache(self, branch_id: int = None) -> None: ...
  ```
- Модуль `backend/app/services/forecast.py` -- оркестрация прогнозов
- Скрипт `scripts/generate_forecast.py` -- batch-генерация

**Критерии приемки (DoD):**
- [ ] Все модели загружаются при старте приложения за < 30 секунд
- [ ] `predict(branch_id, "2026-03")` возвращает данные за каждый рабочий день/час месяца
- [ ] Нет отрицательных значений в прогнозе
- [ ] Повторный запрос того же прогноза выполняется < 100 мс (из кэша)
- [ ] После `POST /api/model/retrain` кэш инвалидирован
- [ ] Некорректный `month` ("abc", "2026-13") -> 422

---

## Блок 3: Frontend -- Дашборд

### Задача 3.1: Страницы приложения

**Описание:** Реализовать 6 страниц React-приложения с навигацией.

**Стек:** React 18, TypeScript, Vite, React Router v6, TailwindCSS (или CSS Modules).

**Роутинг:**

| URL | Страница | Компонент |
|-----|----------|-----------|
| `/` | Главная (Overview) | `Overview.tsx` |
| `/branch/:id` | Детали филиала | `BranchDetail.tsx` |
| `/branch/:id/windows` | Загрузка окон | `Windows.tsx` |
| `/branch/:id/staffing` | Рекомендации по штату | `Staffing.tsx` |
| `/compare` | Сравнение филиалов | `Compare.tsx` |
| `/history/:id` | Исторические данные | `History.tsx` |

#### Страница 1: Главная (Overview)

**Layout:**
```
+------------------------------------------------------------+
| Header: "МФЦ Прогноз" | Month Picker: [2026-03 v]         |
+------------------------------------------------------------+
| KPI Cards (4 шт):                                          |
| [Всего обращений] [Ср. ожидание] [Перегруженных] [Простой] |
+------------------------------------------------------------+
| Top-5 перегруженных филиалов      | Top-5 недогруженных     |
| (таблица с цветовой индикацией)   | (таблица)               |
+------------------------------------------------------------+
| Список всех филиалов (таблица с поиском и сортировкой)     |
| [ID] [Название] [Прогноз обращ.] [Ср.ожидание] [Статус]   |
+------------------------------------------------------------+
```

**KPI Cards:**
- Всего обращений (прогноз на месяц): число + тренд (% к прошлому месяцу)
- Среднее ожидание: минуты + тренд
- Перегруженных филиалов: число (ожидание > 20 мин)
- Простаивающих филиалов: число (загрузка < 30%)

**Таблица филиалов:**
- Поиск по названию (client-side filter)
- Сортировка по любому столбцу
- Клик по строке -> переход на `/branch/:id`

#### Страница 2: Детали филиала (BranchDetail)

**Layout:**
```
+------------------------------------------------------------+
| Breadcrumb: Главная > Филиал Конышевский район              |
| Month Picker: [2026-03 v]                                   |
+------------------------------------------------------------+
| KPI Cards (5 шт):                                          |
| [Обращений/мес] [Ср.ожидание] [Окон] [Сотрудников] [Пик]  |
+------------------------------------------------------------+
| Line Chart: Прогноз обращений по дням                       |
| (x: дни месяца, y: количество, + confidence interval)      |
+------------------------------------------------------------+
| Heatmap: Загрузка "День недели x Час"                       |
| (7 строк x 12 колонок, цвет = кол-во обращений)           |
+------------------------------------------------------------+
| Tabs: [Окна] [Штат] [История]                              |
| -> Переход на соответствующие страницы                      |
+------------------------------------------------------------+
```

**Line Chart:**
- X-axis: дни месяца (1-31)
- Y-axis: суммарные обращения за день
- Основная линия: `predicted_visits` (sum by day)
- Область: `confidence_lower` -- `confidence_upper`
- Tooltip: дата, прогноз, интервал

**Heatmap:**
- Строки: Пн, Вт, Ср, Чт, Пт, Сб, Вс (или только рабочие)
- Колонки: 08:00, 09:00, ..., 19:00
- Цвет ячейки: градиент от зеленого (мало) до красного (много)
- Значение в ячейке: среднее прогнозное кол-во обращений
- Tooltip: день недели, час, прогноз, ср.ожидание

#### Страница 3: Загрузка окон (Windows)

**Layout:**
```
+------------------------------------------------------------+
| Breadcrumb: Главная > Филиал > Окна                         |
| Month Picker: [2026-03 v]                                   |
+------------------------------------------------------------+
| Таблица окон:                                               |
| [Окно] [Ср.загрузка %] [08] [09] [10] ... [19] [Статус]  |
|   1       78%          65  82  91  ...  45    normal        |
|   2       92%          80  95  98  ...  70    overloaded    |
+------------------------------------------------------------+
| Легенда:                                                    |
| [red >85%] [yellow 50-85%] [green 20-50%] [gray <20%]     |
+------------------------------------------------------------+
```

**Цветовая индикация ячеек:**
- Красный (#EF4444): загрузка > 85%
- Желтый (#F59E0B): загрузка 50-85%
- Зеленый (#10B981): загрузка 20-50%
- Серый (#9CA3AF): загрузка < 20%

#### Страница 4: Рекомендации по штату (Staffing)

**Layout:**
```
+------------------------------------------------------------+
| Breadcrumb: Главная > Филиал > Штат                         |
| Month Picker: [2026-03 v]                                   |
+------------------------------------------------------------+
| Summary: Рекомендуется X окон в среднем (текущее: Y)       |
+------------------------------------------------------------+
| Таблица: День x Час -> Требуемое кол-во окон               |
| [Дата]  [08] [09] [10] ... [19] [Макс]                    |
| 02.03    2    3    5   ...   2     5                        |
+------------------------------------------------------------+
| Цветовая индикация:                                         |
| [red: нехватка >=2] [yellow: нехватка 1] [green: ОК]      |
+------------------------------------------------------------+
```

**Логика:**
- `delta = required_windows - current_avg_windows`
- Красный: `delta >= 2` (серьезная нехватка)
- Желтый: `delta == 1` (легкая нехватка)
- Зеленый: `delta <= 0` (достаточно или избыток)

#### Страница 5: Сравнение филиалов (Compare)

**Layout:**
```
+------------------------------------------------------------+
| Multi-select: Выберите филиалы (2-5)                        |
| Month Picker: [2026-03 v]                                   |
+------------------------------------------------------------+
| Bar Chart: Сравнение по прогнозу обращений                  |
+------------------------------------------------------------+
| Таблица сравнения:                                          |
| [Филиал] [Обращ.] [Ожидание] [Обсл.] [Пик час] [Окна]   |
+------------------------------------------------------------+
```

#### Страница 6: Исторические данные (History)

**Layout:**
```
+------------------------------------------------------------+
| Breadcrumb: Главная > Филиал > История                      |
| Date Range Picker: [2023-01] -- [2024-02]                  |
+------------------------------------------------------------+
| Line Chart: Факт (синий) vs Прогноз (оранжевый, пунктир)  |
| (дневная агрегация обращений)                               |
+------------------------------------------------------------+
| Metrics: MAPE = 15.3%, MAE wait = 3.8 мин                  |
+------------------------------------------------------------+
| Heatmap: Фактическая загрузка "День недели x Час"           |
+------------------------------------------------------------+
```

**Входные данные:** API endpoints из задачи 1.4.

**Выходной артефакт:** Компоненты в `frontend/src/pages/` и `frontend/src/components/`.

**Критерии приемки (DoD):**
- [ ] Все 6 страниц рендерятся без ошибок
- [ ] Навигация между страницами работает (React Router)
- [ ] MonthPicker и BranchSelector функционируют
- [ ] Данные загружаются из API (показывается loading spinner при загрузке)
- [ ] Обработка ошибок: при 404/500 от API показывается понятное сообщение
- [ ] Responsive: дашборд читаем на экране 1280px+ (десктоп)
- [ ] Таблица филиалов поддерживает поиск и сортировку
- [ ] Клик по филиалу в таблице ведет на `/branch/:id`

---

### Задача 3.2: API-контракты (TypeScript интерфейсы)

**Описание:** Определить TypeScript-типы для всех данных, получаемых от API.

```typescript
// === Базовые типы ===

interface Branch {
  id: number;
  name: string;
  depart_name_mfc: string | null;
  total_records: number;
  date_range: { from: string; to: string };
}

interface BranchDetail extends Branch {
  num_employees: number;
  num_windows: number;
  avg_daily_visits: number;
  avg_wait_minutes: number;
  avg_service_minutes: number;
  top_services: ServiceStat[];
}

interface ServiceStat {
  service_id: number;
  service_name: string;
  count: number;
}

// === Прогноз ===

interface ForecastPoint {
  date: string;           // "YYYY-MM-DD"
  hour: number;           // 8-19
  predicted_visits: number;
  predicted_avg_wait: number;
  confidence_lower: number;
  confidence_upper: number;
}

interface ForecastResponse {
  branch_id: number;
  branch_name: string;
  month: string;
  data: ForecastPoint[];
  summary: ForecastSummary;
}

interface ForecastSummary {
  total_predicted_visits: number;
  peak_day: string;
  peak_hour: number;
  avg_daily_visits: number;
}

// === Загрузка окон ===

interface WindowHourLoad {
  hour: number;
  load_percent: number;
  avg_visits: number;
}

interface WindowLoad {
  window_number: number;
  avg_daily_load_percent: number;
  load_by_hour: WindowHourLoad[];
  status: 'overloaded' | 'normal' | 'underloaded' | 'idle';
}

interface WindowsResponse {
  branch_id: number;
  month: string;
  windows: WindowLoad[];
}

// === Рекомендации по штату ===

interface StaffingRecommendation {
  date: string;
  hour: number;
  predicted_visits: number;
  avg_service_minutes: number;
  required_windows: number;
  current_windows_avg: number;
  delta: number;
  status: 'understaffed' | 'optimal' | 'overstaffed';
}

interface StaffingResponse {
  branch_id: number;
  month: string;
  recommendations: StaffingRecommendation[];
}

// === Исторические данные ===

interface DailyHistory {
  date: string;
  total_visits: number;
  avg_wait_minutes: number | null;
  avg_service_minutes: number | null;
  peak_hour: number;
}

interface HourlyHistory {
  date: string;
  hour: number;
  total_visits: number;
  avg_wait_minutes: number | null;
  avg_service_minutes: number | null;
  num_windows_active: number;
}

interface HistoryResponse {
  branch_id: number;
  period: { from: string; to: string };
  daily: DailyHistory[];
  hourly: HourlyHistory[];
}

// === Сравнение ===

interface ComparisonRow {
  id: number;
  name: string;
  predicted_total_visits: number;
  predicted_avg_wait: number;
  predicted_avg_service: number;
  predicted_peak_hour: number;
  required_avg_windows: number;
  overloaded_hours_count: number;
}

interface ComparisonResponse {
  month: string;
  branches: ComparisonRow[];
}

// === Обзор ===

interface OverloadedBranch {
  branch_id: number;
  branch_name: string;
  predicted_avg_wait: number;
  overloaded_hours: number;
}

interface UnderloadedBranch {
  branch_id: number;
  branch_name: string;
  predicted_avg_wait: number;
  avg_load_percent: number;
}

interface OverviewResponse {
  month: string;
  total_branches: number;
  total_predicted_visits: number;
  avg_predicted_wait: number;
  top_overloaded: OverloadedBranch[];
  top_underloaded: UnderloadedBranch[];
}

// === Загрузка данных ===

interface UploadResponse {
  status: 'ok' | 'error';
  records_loaded: number;
  records_skipped: number;
  duration_seconds: number;
}

// === Статус модели ===

interface ModelStatus {
  status: 'idle' | 'training' | 'completed' | 'error';
  progress: number;
  total_branches: number;
  current_branch: string | null;
  started_at: string | null;
}
```

**Входные данные:** Спецификация API из задачи 1.4.

**Выходной артефакт:** Файл `frontend/src/types/index.ts`.

**Критерии приемки (DoD):**
- [ ] Все интерфейсы определены и экспортированы
- [ ] Типы совпадают с JSON-ответами API (проверить на реальных данных)
- [ ] Нет `any` типов
- [ ] `tsc --noEmit` проходит без ошибок

---

### Задача 3.3: Визуализации

**Описание:** Реализовать компоненты графиков и таблиц с цветовой индикацией.

**Библиотека:** ECharts (через `echarts-for-react`) -- рекомендуется за поддержку heatmap из коробки. Альтернатива: Recharts (проще, но нет heatmap).

#### Компонент 1: LineChart (Прогноз по дням)

**Props:**
```typescript
interface LineChartProps {
  data: { date: string; value: number; lower: number; upper: number }[];
  title?: string;
  yAxisLabel?: string;
}
```

**Функциональность:**
- Линия `value` + полупрозрачная область `[lower, upper]`
- X-axis: даты
- Tooltip при наведении: дата, значение, интервал
- Zoom/pan по оси X (для больших периодов)

#### Компонент 2: HeatmapChart (Загрузка по часам)

**Props:**
```typescript
interface HeatmapChartProps {
  data: { dayOfWeek: number; hour: number; value: number }[];
  title?: string;
  colorRange?: [string, string]; // [min color, max color]
}
```

**Функциональность:**
- Сетка 7x12 (Пн-Вс x 08:00-19:00)
- Цвет ячейки: градиент от минимума к максимуму
- Значение в ячейке: число
- Tooltip: день недели (текст), час, значение

#### Компонент 3: LoadIndicator (Цветовой индикатор)

**Props:**
```typescript
interface LoadIndicatorProps {
  value: number;          // процент загрузки 0-100
  showValue?: boolean;    // показывать число
}
```

**Цветовая схема:**
```
value > 85  -> bg-red-500    (#EF4444), text-white  -> "overloaded"
value > 50  -> bg-yellow-400 (#FBBF24), text-black  -> "normal"
value > 20  -> bg-green-500  (#10B981), text-white  -> "underloaded"
value <= 20 -> bg-gray-300   (#D1D5DB), text-gray   -> "idle"
```

#### Компонент 4: StaffingTable (Таблица штата)

**Props:**
```typescript
interface StaffingTableProps {
  recommendations: StaffingRecommendation[];
  dates: string[];
}
```

**Функциональность:**
- Строки: даты
- Колонки: часы (08-19)
- Значение ячейки: `required_windows`
- Цвет ячейки: красный (delta >= 2), желтый (delta == 1), зеленый (delta <= 0)
- Итоговый столбец: максимум за день

#### Компонент 5: BarChart (Сравнение филиалов)

**Props:**
```typescript
interface BarChartProps {
  data: { name: string; value: number }[];
  title?: string;
  yAxisLabel?: string;
  color?: string;
}
```

**Функциональность:**
- Горизонтальные бары (для длинных названий филиалов)
- Сортировка по значению (descending)
- Tooltip: название, значение

**Входные данные:** Данные от API (через TypeScript интерфейсы из задачи 3.2).

**Выходной артефакт:** Компоненты в `frontend/src/components/`.

**Критерии приемки (DoD):**
- [ ] LineChart: отображает данные с confidence interval, tooltip работает
- [ ] HeatmapChart: корректная сетка 7x12, цвета соответствуют значениям
- [ ] LoadIndicator: корректные цвета для всех 4 диапазонов
- [ ] StaffingTable: ячейки окрашены по delta, отображается required_windows
- [ ] BarChart: горизонтальные бары, сортировка, tooltip
- [ ] Все компоненты принимают данные через props (нет hardcoded данных)
- [ ] Компоненты корректно обрабатывают пустые данные (empty state)
- [ ] Нет console errors при рендере

---

## Блок 4: Инфраструктура

### Задача 4.1: Docker Compose

**Описание:** Настроить контейнеризацию для локального запуска и деплоя.

**docker-compose.yml:**

```yaml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data:ro           # CSV данные (read-only)
      - ./models:/app/models          # Обученные модели
      - sqlite-data:/app/db           # SQLite файл
    environment:
      - DATABASE_URL=sqlite:///app/db/mfc.db
      - MODEL_DIR=/app/models
      - CSV_DIR=/app/data
      - CORS_ORIGINS=http://localhost:5173,http://localhost:3000
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend
    environment:
      - VITE_API_URL=http://localhost:8000/api

volumes:
  sqlite-data:
```

**Backend Dockerfile:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Frontend Dockerfile:**

```dockerfile
# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**Frontend nginx.conf:**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Входные данные:** Код backend и frontend.

**Выходной артефакт:**
- `docker-compose.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `frontend/nginx.conf`

**Критерии приемки (DoD):**
- [ ] `docker-compose build` завершается без ошибок
- [ ] `docker-compose up` запускает оба сервиса
- [ ] Backend доступен на `http://localhost:8000/docs` (Swagger)
- [ ] Frontend доступен на `http://localhost:3000`
- [ ] Frontend корректно проксирует API-запросы к backend
- [ ] SQLite-файл персистентен при перезапуске (volume)
- [ ] Модели доступны backend'у через volume mount

---

### Задача 4.2: Скрипты инициализации и обучения

**Описание:** Создать CLI-скрипты для типичных операций.

#### Скрипт 1: `scripts/init_db.py`

**Назначение:** Создание схемы БД и загрузка всех CSV-данных.

**Интерфейс:**
```bash
python scripts/init_db.py --csv-dir ./data --db-url sqlite:///mfc.db [--drop-existing]
```

**Аргументы:**
- `--csv-dir`: путь к папке с CSV (по умолчанию: `./data`)
- `--db-url`: строка подключения к БД (по умолчанию: из env `DATABASE_URL`)
- `--drop-existing`: удалить и пересоздать таблицы (по умолчанию: false)

**Процесс:**
1. Создать таблицы (или пересоздать если `--drop-existing`)
2. Загрузить справочники: branches, services, employees
3. Загрузить основные данные: queue_records (14 файлов), employee_roles (14 файлов)
4. Загрузить связи: employee_services
5. Агрегировать: заполнить hourly_stats
6. Вывести итоговую статистику

**Выход (stdout):**
```
[2026-02-09 15:00:00] Starting database initialization...
[2026-02-09 15:00:01] Creating tables... OK
[2026-02-09 15:00:02] Loading branches... 85 records
[2026-02-09 15:00:03] Loading services... 156 records
[2026-02-09 15:00:10] Loading employees... 412 records (14 files, 87 duplicates resolved)
[2026-02-09 15:03:00] Loading queue_records... 1,512,345 records (14 files, 23 errors skipped)
[2026-02-09 15:04:30] Loading employee_roles... 98,234 records (14 files)
[2026-02-09 15:04:35] Loading employee_services... 2,345 records
[2026-02-09 15:06:00] Aggregating hourly_stats... 152,880 records
[2026-02-09 15:06:01] === Summary ===
                      branches:        85
                      employees:      412
                      services:       156
                      queue_records:  1,512,345
                      employee_roles: 98,234
                      hourly_stats:   152,880
                      Total time:     6m 01s
[2026-02-09 15:06:01] Done.
```

#### Скрипт 2: `scripts/train_model.py`

**Назначение:** Обучение Prophet-моделей для всех филиалов.

**Интерфейс:**
```bash
python scripts/train_model.py --db-url sqlite:///mfc.db --model-dir ./models [--branch-id 176] [--test-split 2023-10-01]
```

**Аргументы:**
- `--db-url`: строка подключения к БД
- `--model-dir`: папка для сохранения моделей (по умолчанию: `./models`)
- `--branch-id`: обучить только один филиал (для отладки)
- `--test-split`: дата разбиения для backtesting (по умолчанию: None -- обучить на всех данных)

**Процесс:**
1. Получить список филиалов из БД
2. Для каждого филиала:
   a. Подготовить данные (`prepare_prophet_data`)
   b. Обучить модель
   c. Если `--test-split`: вычислить метрики на test
   d. Сохранить модель и метрики
3. Сохранить `training_metadata.json`

#### Скрипт 3: `scripts/generate_forecast.py`

**Назначение:** Batch-генерация прогнозов на указанный месяц для всех филиалов.

**Интерфейс:**
```bash
python scripts/generate_forecast.py --model-dir ./models --db-url sqlite:///mfc.db --month 2026-03
```

**Аргументы:**
- `--model-dir`: папка с обученными моделями
- `--db-url`: строка подключения к БД
- `--month`: месяц прогноза (формат `YYYY-MM`)

**Процесс:**
1. Загрузить все модели
2. Для каждого филиала:
   a. Сгенерировать future DataFrame
   b. Выполнить predict
   c. Сохранить результат в таблицу `forecasts`
3. Вывести итоговую статистику

**Входные данные:** CSV-файлы (init_db), БД (train_model, generate_forecast), модели (generate_forecast).

**Выходной артефакт:**
- `scripts/init_db.py`
- `scripts/train_model.py`
- `scripts/generate_forecast.py`

**Критерии приемки (DoD):**
- [ ] `scripts/init_db.py` выполняется без ошибок и загружает все данные
- [ ] `scripts/init_db.py --drop-existing` пересоздает таблицы
- [ ] `scripts/train_model.py` обучает модели для >= 40 филиалов
- [ ] `scripts/train_model.py --branch-id 176` обучает только один филиал
- [ ] `scripts/generate_forecast.py --month 2026-03` заполняет таблицу `forecasts`
- [ ] Все скрипты поддерживают `--help` и корректно обрабатывают ошибки
- [ ] Все скрипты выводят прогресс и итоговую статистику
- [ ] Все скрипты работают из Docker-контейнера

---

## Зависимости между задачами

```
1.1 (Структура) ──┬──> 1.2 (ETL) ──> 1.3 (Схема БД) ──> 2.1 (Подготовка данных)
                  │                                         │
                  │                                         v
                  │                                    2.2 (Обучение) ──> 2.3 (Валидация)
                  │                                         │
                  │                                         v
                  │                                    2.4 (Inference) ──> 1.4 (REST API)
                  │                                                            │
                  └──> 3.2 (TS типы) ──> 3.3 (Визуализации) ──> 3.1 (Страницы)
                                                                       │
                  4.1 (Docker) <────────────────────────────────────────┘
                       │
                       v
                  4.2 (Скрипты)
```

**Критический путь:** 1.1 -> 1.2 -> 1.3 -> 2.1 -> 2.2 -> 2.4 -> 1.4 -> 3.1 -> 4.1

**Параллельная работа возможна:**
- Frontend (3.2, 3.3) можно начинать параллельно с backend (1.2, 1.3) -- используя mock-данные
- Docker (4.1) можно настраивать параллельно с разработкой
- Backtesting (2.3) можно делать параллельно с inference API (2.4)

---

## Требования к зависимостям

### Backend (`requirements.txt`)

```
fastapi==0.109.0
uvicorn[standard]==0.27.0
sqlalchemy==2.0.25
pydantic==2.5.3
python-multipart==0.0.6
prophet==1.1.5
pandas==2.2.0
numpy==1.26.3
scikit-learn==1.4.0
joblib==1.3.2
holidays==0.41
httpx==0.26.0
pytest==7.4.4
pytest-asyncio==0.23.3
```

### Frontend (`package.json` dependencies)

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.21.0",
    "echarts": "^5.4.3",
    "echarts-for-react": "^3.0.2",
    "axios": "^1.6.5",
    "@tanstack/react-query": "^5.17.0",
    "tailwindcss": "^3.4.1",
    "clsx": "^2.1.0"
  },
  "devDependencies": {
    "typescript": "^5.3.3",
    "vite": "^5.0.12",
    "@types/react": "^18.2.48",
    "@types/react-dom": "^18.2.18"
  }
}
```

---

## Нефункциональные требования

| Требование | Значение |
|------------|----------|
| Время ответа API (GET) | < 2 сек |
| Время ответа API (прогноз, из кэша) | < 100 мс |
| Время загрузки страницы | < 3 сек |
| Время обучения всех моделей | < 30 мин |
| Время загрузки CSV (init_db) | < 10 мин |
| Одновременных пользователей | >= 5 |
| Поддерживаемые браузеры | Chrome 100+, Firefox 100+, Edge 100+ |
| Минимальное разрешение экрана | 1280x720 |
| Язык интерфейса | Русский |
