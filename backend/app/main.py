"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Create all tables on startup."""
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="MFC Forecast API",
    description="API for MFC window load forecasting system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
origins = settings.CORS_ORIGINS
if origins == "*":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    origin_list = [o.strip() for o in origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Import and include routers
# NOTE: analytics router must be included BEFORE branches/forecast routers
# because /api/branches/compare must match before /api/branches/{branch_id}
from app.api.analytics import router as analytics_router
from app.api.branches import router as branches_router
from app.api.forecast import router as forecast_router
from app.api.data import router as data_router

app.include_router(analytics_router)
app.include_router(branches_router)
app.include_router(forecast_router)
app.include_router(data_router)


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
