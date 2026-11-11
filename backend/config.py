"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
import os
from pathlib import Path
import secrets


@dataclass(frozen=True)
class Settings:
    """Runtime settings for database connectivity, JWT auth, uploads, and local seeding."""

    app_name: str
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    token_expire_minutes: int
    upload_dir: Path
    max_upload_bytes: int
    auto_seed: bool


def load_settings() -> Settings:
    """Load TriageDesk settings with safe local SQLite defaults."""
    env_mode = os.getenv("TRIAGEDESK_ENV", "development").lower()
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if not secret:
        if env_mode == "production":
            raise RuntimeError("JWT_SECRET_KEY must be set in production mode.")
        secret = secrets.token_urlsafe(32) if env_mode == "ephemeral" else "triagedesk-local-dev-secret-change-before-prod-9821"

    upload_root = Path(os.getenv("TRIAGEDESK_UPLOAD_DIR", "./uploads")).resolve()
    upload_root.mkdir(parents=True, exist_ok=True)

    return Settings(
        app_name="TriageDesk",
        database_url=os.getenv("DATABASE_URL", "sqlite:///./triagedesk.db"),
        jwt_secret=secret,
        jwt_algorithm="HS256",
        token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480")),
        upload_dir=upload_root,
        max_upload_bytes=5 * 1024 * 1024,
        auto_seed=os.getenv("AUTO_SEED", "true").lower() in {"1", "true", "yes"},
    )


settings = load_settings()
