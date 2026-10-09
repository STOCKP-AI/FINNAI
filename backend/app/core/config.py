"""Settings from environment variables and .env files (never from code).

Files read, later ones overriding earlier ones: ml/.env, .env (repository root), backend/.env.
Variables set in the environment (Render, GitHub Actions) win over all files.

Prototype AI (no paid key): LLM_PROVIDER=gemini with a free Google AI Studio key;
LLM_FALLBACK_PROVIDER=groq answers automatically when Gemini is busy or rate-limited;
LLM_PROVIDER=mock needs no key (tests, demo fallback).
"""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/app/core -> repository root
ENV_FILES = (REPO_ROOT / "ml" / ".env", REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env")

Provider = Literal["mock", "gemini", "groq", "github", "openai_compat"]

PROVIDER_DEFAULTS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.8-flash"),
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "github": ("https://models.github.ai/inference", "openai/gpt-4.1-mini"),
}


class LLMConfig:
    """Resolved connection details for one OpenAI-compatible model (or the mock)."""

    def __init__(self, provider, base_url, model, api_key, timeout_s):
        default_url, default_model = PROVIDER_DEFAULTS.get(provider, (None, None))
        self.provider = provider
        self.base_url = base_url or default_url
        self.model = model or default_model or "mock"
        self.api_key = api_key.get_secret_value() if api_key else None
        self.timeout_s = timeout_s

    @property
    def problem(self):
        """Why this configuration cannot be used, or None."""
        if self.provider == "mock":
            return None
        if not self.api_key:
            return f"LLM_PROVIDER={self.provider} needs an API key"
        if not self.base_url:
            return f"LLM_PROVIDER={self.provider} needs LLM_BASE_URL"
        return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    database_url: SecretStr | None = None

    llm_provider: Provider = "mock"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_s: float = 30.0

    # Automatic fallback when the main model is busy or rate-limited (HTTP 429/503).
    llm_fallback_provider: Provider | None = None
    llm_fallback_base_url: str | None = None
    llm_fallback_model: str | None = None
    llm_fallback_api_key: SecretStr | None = None

    # Second model for the eval judge (a different model from the one being tested).
    judge_provider: Provider | None = None
    judge_base_url: str | None = None
    judge_model: str | None = None
    judge_api_key: SecretStr | None = None

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    ip_hash_pepper: SecretStr | None = None
    chat_daily_limit: int = Field(10, ge=1, le=1000)
    trust_proxy_headers: bool = False  # true only behind a proxy that sets X-Forwarded-For (Render)
    docs_enabled: bool = True
    nse_holidays: Annotated[list[date], NoDecode] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            v = [s.strip() for s in v.split(",") if s.strip()]
        for origin in v:
            if "*" in origin or origin.endswith("/"):
                raise ValueError(f"CORS origin must be exact, without '*' or a trailing '/': {origin!r}")
        return v

    @field_validator("nse_holidays", mode="before")
    @classmethod
    def _split_dates(cls, v):
        if isinstance(v, str):
            v = [s.strip() for s in v.split(",") if s.strip()]
        return v

    def llm(self):
        return LLMConfig(
            self.llm_provider, self.llm_base_url, self.llm_model, self.llm_api_key, self.llm_timeout_s
        )

    def llm_fallback(self):
        if not self.llm_fallback_provider:
            return None
        return LLMConfig(
            self.llm_fallback_provider,
            self.llm_fallback_base_url,
            self.llm_fallback_model,
            self.llm_fallback_api_key,
            self.llm_timeout_s,
        )

    def judge(self):
        if not self.judge_provider:
            return None
        return LLMConfig(
            self.judge_provider, self.judge_base_url, self.judge_model, self.judge_api_key, self.llm_timeout_s
        )


@lru_cache
def get_settings():
    return Settings()
