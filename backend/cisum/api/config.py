"""Settings, read from CISUM_* environment variables (or a .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CISUM_", env_file=".env", extra="ignore")

    # Storage and database
    database_url: str = "sqlite:///./data/cisum.db"
    storage: str = "local"  # local | s3
    storage_dir: Path = Path("./data/storage")
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None  # e.g. http://minio:9000
    s3_public_endpoint_url: str | None = None  # endpoint browsers use for presigned uploads, if different
    s3_region: str = "us-east-1"
    s3_prefix: str = ""

    # Jobs
    queue: str = "thread"  # rq (Redis workers) | thread (in the API process) | sync (inline, for tests)
    redis_url: str = "redis://localhost:6379/0"
    job_timeout_s: int = 1800

    # Engine
    separator: str = "auto"
    demucs_model: str = "htdemucs"
    beats: str = "auto"
    melody: str = "auto"
    notes: str = "auto"
    device: str | None = None

    # Limits and policy
    max_upload_mb: int = 200  # room for videos; uploads are deleted once they're analyzed
    max_duration_s: float = 600.0
    delete_audio_after_processing: bool = True
    strike_limit: int = 3
    auto_hide_on_copyright_report: bool = True
    admin_emails: str = ""  # comma-separated; these accounts become admins when they register

    # Web
    single_user: bool = False  # personal mode for running on your own computer: no accounts, no login
    cookie_secure: bool = False  # set true behind HTTPS
    session_days: int = 30
    allowed_origins: str = ""  # comma-separated, only needed when the web app is on another origin
    web_dist: Path | None = None  # serve the built web app from here (defaults to ../web/dist if it exists)
    trust_proxy_headers: bool = False  # use X-Forwarded-For for the consent record's IP

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
