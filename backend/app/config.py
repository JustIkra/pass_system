"""Application configuration using pydantic-settings."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    DATABASE_URL: str = "postgresql+psycopg2://mfc_user:mfc_pass@localhost:5432/mfc_db"
    DATA_DIR: str = str(
        Path(__file__).resolve().parent.parent.parent / "Исходные данные АИС"
    )
    MODELS_DIR: str = str(Path(__file__).resolve().parent.parent.parent / "models")
    CORS_ORIGINS: str = "*"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
