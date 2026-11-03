"""Environment-backed configuration for the workflow and local demo."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
    )

    groq_api_key: str | None = None
    groq_model_primary: str = Field(default="openai/gpt-oss-120b", min_length=1)
    groq_model_fast: str = Field(default="openai/gpt-oss-20b", min_length=1)
    groq_timeout_seconds: float = Field(default=30, gt=0)
    groq_max_retries: int = Field(default=3, ge=0, le=10)
    llm_mode: Literal["fake", "groq"] = "fake"
    database_url: str = Field(
        default="postgresql+asyncpg://maintenance:maintenance@localhost:5432/maintenance",
        min_length=1,
    )
    hitl_min_confidence: float = Field(default=0.70, ge=0, le=1)
    spend_approval_threshold_usd: float = Field(default=5000, ge=0)
    alert_quiet_period_minutes: int = Field(default=5, ge=0)
    alert_dedup_window_minutes: int = Field(default=15, ge=0)
    sla_tier1_minutes: int = Field(default=15, gt=0)
    sla_tier2_minutes: int = Field(default=60, gt=0)
    sla_tier3_minutes: int = Field(default=240, gt=0)
    pipeline_mode: Literal["live", "shadow"] = "live"
    cmms_adapter: Literal["mock", "maximo", "sap_pm"] = "mock"
    inventory_adapter: Literal["mock"] = "mock"
    scheduler_adapter: Literal["mock"] = "mock"
    labor_rate_usd_per_hour: float = Field(default=110, ge=0)
    vite_api_base_url: str = Field(default="http://localhost:8000/api/v1", min_length=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
