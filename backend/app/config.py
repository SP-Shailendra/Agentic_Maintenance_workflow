"""Environment-backed configuration for the workflow and local demo."""

import os
from functools import lru_cache

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseModel, ConfigDict

    def SettingsConfigDict(**kwargs: object) -> ConfigDict:
        return ConfigDict(**kwargs)

    class BaseSettings(BaseModel):
        model_config = ConfigDict(extra="ignore")

        def __init__(self, **data: object) -> None:
            for name in type(self).model_fields:
                environment_value = os.getenv(name.upper())
                if environment_value is not None:
                    data.setdefault(name, environment_value)
            super().__init__(**data)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str | None = None
    groq_model_primary: str = "openai/gpt-oss-120b"
    groq_model_fast: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: float = 30
    groq_max_retries: int = 3
    llm_mode: str = "fake"
    database_url: str = "postgresql+asyncpg://maintenance:maintenance@localhost:5432/maintenance"
    hitl_min_confidence: float = 0.70
    spend_approval_threshold_usd: float = 5000
    alert_quiet_period_minutes: int = 5
    alert_dedup_window_minutes: int = 15
    sla_tier1_minutes: int = 15
    sla_tier2_minutes: int = 60
    sla_tier3_minutes: int = 240
    pipeline_mode: str = "live"
    cmms_adapter: str = "mock"
    inventory_adapter: str = "mock"
    scheduler_adapter: str = "mock"
    labor_rate_usd_per_hour: float = 110
    vite_api_base_url: str = "http://localhost:8000/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
