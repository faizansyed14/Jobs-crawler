from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/gulf_crawler",
        alias="DATABASE_URL",
    )
    crawler_user_agent: str = Field(
        default="GulfJobCrawler/1.0 (+contact@example.com)",
        alias="CRAWLER_USER_AGENT",
    )
    crawler_contact_email: str = Field(
        default="contact@example.com",
        alias="CRAWLER_CONTACT_EMAIL",
    )
    min_delay_seconds: float = Field(default=4.0, alias="MIN_DELAY_SECONDS")
    max_delay_seconds: float = Field(default=30.0, alias="MAX_DELAY_SECONDS")
    location_gap_seconds: float = Field(default=5.0, alias="LOCATION_GAP_SECONDS")
    max_pages_per_run: int = Field(default=20, alias="MAX_PAGES_PER_RUN")
    max_consecutive_failures: int = Field(default=3, alias="MAX_CONSECUTIVE_FAILURES")
    empty_page_stop_streak: int = Field(default=2, alias="EMPTY_PAGE_STOP_STREAK")
    uncapped_max_pages: int = Field(default=500, alias="UNCAPPED_MAX_PAGES")
    cookie_dir: Path = Field(default=Path("./cookies"), alias="COOKIE_DIR")
    browser_profile_dir: Path = Field(
        default=Path("./browser_profiles"),
        alias="BROWSER_PROFILE_DIR",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    def ensure_dirs(self) -> None:
        self.cookie_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings