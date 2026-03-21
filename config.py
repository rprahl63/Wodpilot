"""WODpilot configuration – loaded from environment variables."""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    # Telegram
    telegram_token: str = field(default_factory=lambda: os.environ["TELEGRAM_TOKEN"])
    admin_telegram_id: int = field(
        default_factory=lambda: int(os.environ["ADMIN_TELEGRAM_ID"])
    )

    # Supabase
    supabase_url: str = field(default_factory=lambda: os.environ["SUPABASE_URL"])
    supabase_service_key: str = field(
        default_factory=lambda: os.environ["SUPABASE_SERVICE_KEY"]
    )

    # Encryption
    encryption_key: str = field(
        default_factory=lambda: os.environ["ENCRYPTION_KEY"]
    )

    # Web UI
    web_secret_key: str = field(
        default_factory=lambda: os.environ.get("WEB_SECRET_KEY", "change-me-in-prod")
    )
    web_admin_password: str = field(
        default_factory=lambda: os.environ.get("WEB_ADMIN_PASSWORD", "admin")
    )
    web_port: int = field(
        default_factory=lambda: int(os.environ.get("WEB_PORT", "8080"))
    )

    # OpenAI (embeddings only)
    openai_api_key: Optional[str] = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY")
    )

    # Scheduling (cron expressions)
    garmin_sync_cron: str = field(
        default_factory=lambda: os.environ.get("GARMIN_SYNC_CRON", "0 5 * * *")
    )
    wod_scrape_cron: str = field(
        default_factory=lambda: os.environ.get("WOD_SCRAPE_CRON", "30 5 * * *")
    )
    morning_briefing_cron: str = field(
        default_factory=lambda: os.environ.get("MORNING_BRIEFING_CRON", "0 7 * * *")
    )

    # Defaults
    default_llm_model: str = field(
        default_factory=lambda: os.environ.get(
            "DEFAULT_LLM_MODEL", "claude-sonnet-4-20250514"
        )
    )
    max_conversation_messages: int = 20
    max_api_calls_per_day: int = field(
        default_factory=lambda: int(os.environ.get("MAX_API_CALLS_PER_DAY", "50"))
    )

    # ffmpeg
    ffmpeg_path: str = field(
        default_factory=lambda: os.environ.get("FFMPEG_PATH", "ffmpeg")
    )

    # Data directory
    data_dir: str = field(
        default_factory=lambda: os.environ.get("DATA_DIR", "/data")
    )


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
