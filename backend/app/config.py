from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://answerwatch:answerwatch@localhost:5433/answerwatch"

    gemini_api_key: str = ""
    gemini_probe_model: str = "gemini-3.8-flash"
    gemini_internal_model: str = "gemini-3.5-flash-lite"
    gemini_embed_model: str = "gemini-embedding-001"
    embedding_dim: int = 768
    groq_api_key: str = ""
    groq_probe_model: str = "openai/gpt-oss-120b"
    groq_internal_model: str = "openai/gpt-oss-120b"
    groq_tokens_per_minute: int = 8000
    groq_max_output_tokens: int = 800
    openrouter_api_key: str = ""
    openrouter_memory_model: str = "nvidia/nemotron-3.5-super-vl:free"

    gemini_max_concurrency: int = 2
    groq_max_concurrency: int = 1
    # a 429 with a longer wait than this (or a used-up daily quota) stops the provider for the run
    groq_daily_stop_seconds: int = 900
    gemini_daily_stop_seconds: int = 900
    page_cache_days: int = 7

    fetch_user_agent: str = "AnswerWatchBot/0.1 (+your-email)"
    # contact (email or URL) for the Wikipedia User-Agent; falls back to FETCH_USER_AGENT
    wikipedia_contact: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_app_password: str = ""
    email_from_name: str = "AnswerWatch"

    admin_password: str = "change-me"
    # one or more allowed browser origins, comma separated (CORS)
    frontend_origin: str = "http://localhost:5173"
    dashboard_url: str = "http://localhost:5173"
    timezone: str = "Europe/Helsinki"

    # tested-engine list; the default file lives in backend/config so the Docker image has it
    engines_file: Path = BACKEND_DIR / "config" / "engines.yaml"

    job_runner: str = "local"
    github_repo: str = "your-user/answerwatch"
    github_ref: str = "main"
    github_dispatch_token: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    @field_validator("database_url", mode="before")
    @classmethod
    def blank_database_url_uses_default(cls, value: str | None) -> str:
        # An empty DATABASE_URL= line in .env should mean "use the local default".
        return value or cls.model_fields["database_url"].default


@lru_cache
def get_settings() -> Settings:
    return Settings()
