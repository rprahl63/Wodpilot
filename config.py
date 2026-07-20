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
    # Public base URL of the web app – used to build athlete magic links.
    dashboard_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "DASHBOARD_BASE_URL", "http://localhost:8080"
        ).rstrip("/")
    )
    login_token_ttl_minutes: int = field(
        default_factory=lambda: int(os.environ.get("LOGIN_TOKEN_TTL_MINUTES", "15"))
    )

    # Requesty router – chat models and embeddings both go through here.
    requesty_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "REQUESTY_BASE_URL", "https://router.requesty.ai/v1"
        )
    )
    # Optional service-wide key. Embeddings normally use the per-user key
    # (BYOK); this is only the fallback when no user context is available.
    requesty_api_key: Optional[str] = field(
        default_factory=lambda: os.environ.get("REQUESTY_API_KEY")
    )
    embedding_model: str = field(
        default_factory=lambda: os.environ.get(
            "EMBEDDING_MODEL", "openai/text-embedding-3-large"
        )
    )
    # Speech-to-text for Telegram voice messages, also via Requesty (BYOK).
    transcription_model: str = field(
        default_factory=lambda: os.environ.get(
            "TRANSCRIPTION_MODEL", "openai/gpt-4o-mini-transcribe"
        )
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
    weekly_plan_ask_cron: str = field(
        default_factory=lambda: os.environ.get("WEEKLY_PLAN_ASK_CRON", "0 10 * * sun")
    )
    weekly_plan_fallback_cron: str = field(
        default_factory=lambda: os.environ.get(
            "WEEKLY_PLAN_FALLBACK_CRON", "0 18 * * sun"
        )
    )

    # Defaults
    default_llm_model: str = field(
        default_factory=lambda: os.environ.get(
            "DEFAULT_LLM_MODEL", "anthropic/claude-sonnet-4-5"
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

    # Pi-agent microservice
    pi_agent_url: str = field(
        default_factory=lambda: os.environ.get("PI_AGENT_URL", "http://pi-agent-service:3001")
    )
    internal_api_token: str = field(
        default_factory=lambda: os.environ.get("INTERNAL_API_TOKEN", "")
    )


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
