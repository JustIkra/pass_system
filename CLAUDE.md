# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Summary

MFC Forecast Dashboard — web app for predicting window load in Russian government service centers (МФЦ). Analyzes 1.7GB of historical CSV queue data (2023-2024) across 44 branches, trains Prophet time-series models per branch, and displays forecasts via an interactive React dashboard.

## Commands

### Setup & Data Pipeline
```bash
mkdir -p models
# Start PostgreSQL (via Docker or system)
docker compose up -d postgres

# ETL: CSV -> PostgreSQL (~5-10 min)
python3 scripts/init_db.py --data-dir "./Исходные данные АИС"

# Train 44 Prophet models (~10-20 min CPU, ~5-10 min GPU)
python3 scripts/train_model.py --validate
python3 scripts/train_model.py --validate --gpu                          # GPU-accelerated training
python3 scripts/train_model.py --branch-id 176                          # Train single branch (debug)

# Generate forecast for a month
python3 scripts/generate_forecast.py --month 2026-03
python3 scripts/generate_forecast.py --month 2026-03 --branch-id 176   # Single branch forecast
```

### Development
```bash
# Backend (FastAPI)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000       # API at localhost:8000, Swagger at /docs

# Frontend (React + Vite)
cd frontend && npm install
npm run dev                                      # Dev server at localhost:5173 (proxies /api -> :8000)
npm run build                                    # Production build (tsc -b && vite build)
npx tsc --noEmit                                 # Type-check only

# Docker (all services: postgres + backend + frontend)
docker compose up --build                        # PostgreSQL :5432, Backend :8000, Frontend :3000
```

### Validation
```bash
# Python syntax check (no test framework yet)
python3 -c "import ast, glob; [ast.parse(open(f).read()) for f in glob.glob('backend/app/**/*.py', recursive=True)]; print('OK')"

# TypeScript type check
cd frontend && npx tsc --noEmit
```

## Architecture

### Data Flow
```
CSV files (1.7GB) → scripts/init_db.py → PostgreSQL (mfc_db)
                                              ↓
                    scripts/train_model.py → Prophet models (models/*.pkl)
                                              ↓
                    scripts/generate_forecast.py → forecasts table in PostgreSQL
                                              ↓
                    FastAPI backend (multi-worker) ← REST API → React frontend
```

### Backend (`backend/app/`)
- **main.py** — FastAPI app with CORS, lifespan (auto-creates tables), 4 routers
- **models.py** — 7 SQLAlchemy tables: branches, employees, services, queue_records, employee_roles, hourly_stats, forecasts
- **schemas.py** — Pydantic response models for all endpoints
- **api/** — 4 route modules: branches, forecast (windows/staffing/history), analytics (compare/overview), data (upload/retrain)
- **services/etl.py** — CSV parsing (delimiter `;`, dates DD.MM.YYYY, times HH:MM:SS), batch loading, hourly_stats aggregation
- **services/forecast_service.py** — Forecast queries, window load calculation, staffing recommendations
- **ml/utils.py** — REGRESSOR_COLUMNS, add_regressors(), wMAPE metric, Russian holidays
- **ml/training.py** — Prophet model training: zero-fill gaps, log1p transform, backtesting with expm1 inverse
- **ml/prediction.py** — Forecast generation with expm1 inverse transform, confidence intervals, DB persistence
- **config.py** — Settings via env vars: DATABASE_URL, DATA_DIR, MODELS_DIR, CORS_ORIGINS

### Frontend (`frontend/src/`)
- **React 18 + TypeScript + Vite 6 + Tailwind CSS v4 + ECharts**
- **Routes:** `/` (Overview), `/branches/:id` (Branch with 4 tabs: Forecast/Windows/Staffing/History), `/compare`
- **api/client.ts** — Typed fetch wrapper, uses `VITE_API_URL` or defaults to `/api`
- **types/index.ts** — All TypeScript interfaces matching backend Pydantic schemas
- **hooks/useApi.ts** — Generic data fetching hook with loading/error/refetch

### Key API Endpoints
- `GET /api/branches` — List all branches
- `GET /api/branches/{id}/forecast?month=YYYY-MM` — Hourly forecast data
- `GET /api/branches/{id}/windows?month=YYYY-MM` — Window load with status
- `GET /api/branches/{id}/staffing?month=YYYY-MM` — Required staff per hour
- `GET /api/branches/compare?ids=1,2,3&month=YYYY-MM` — Compare 2-5 branches
- `GET /api/analytics/overview?month=YYYY-MM` — Network-wide stats

## Important Conventions

- **Working hours:** MFC operates 8:00-20:00 → use `range(8, 20)`, not `range(8, 18)`
- **Wait time units:** Backend returns wait time in **minutes**. Frontend must NOT divide by 60 again
- **employee_window is STRING**, not number (values like "A1", "B2", "П14")
- **CSV format:** delimiter `;`, encoding UTF-8, dates DD.MM.YYYY, times HH:MM:SS, empty = NULL
- **Backend field naming:** snake_case (`from_date`, `to_date`). Frontend types must match exactly
- **Nullable fields:** BranchComparison fields (`predicted_avg_wait`, `predicted_avg_service`, `predicted_peak_hour`) can be null — use `| null` in TypeScript
- **Prophet models:** Need minimum 360 **original** data points per branch (before zero-fill); skip branches with insufficient data
- **ML data pipeline:** `prepare_training_data` fills missing hourly slots with 0 (skipping Sundays), then applies `np.log1p(y)`. All models train on log-scale data.
- **ML inverse transform:** Prediction/validation must apply `np.expm1()` + `np.maximum(..., 0.0)` to convert back from log-scale
- **Regressor columns:** Defined once in `REGRESSOR_COLUMNS` (utils.py). Never hardcode `["is_month_start", ...]` — always use the constant
- **Validation metric:** wMAPE (weighted MAPE), not standard MAPE. Formula: `sum(|actual-predicted|) / sum(actual) * 100`
- **All UI text in Russian.** Numbers formatted with space separator (1 234), decimal comma (78,5%)

## Documentation
- `docs/product_vision.md` — User stories, MVP scope, success metrics
- `docs/technical_requirements.md` — Full tech spec: DB schema, API contracts, component specs
- `docs/ux_requirements.md` — Color system, page layouts, UX criteria
- `docs/test_plan.md` — 80+ test cases, acceptance scenarios, DoD
