from __future__ import annotations
import json
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict


class _CsvEnvSource(EnvSettingsSource):
    """Custom env source that allows non-JSON complex values (e.g. CSV strings).

    pydantic-settings >=2.x tries to JSON-decode complex fields (list, dict, etc.)
    before validators run.  This subclass falls back to returning the raw string on
    JSON parse failure so that field validators can do their own conversion (e.g.
    splitting a comma-separated string into a list).
    """

    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value  # pass raw string; field validators will handle it


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    backend_port: int = 8000
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):  # type: ignore[override]
        return (_CsvEnvSource(settings_cls),)


@lru_cache
def get_settings() -> Settings:
    return Settings()
