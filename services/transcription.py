"""
Speech-to-text for Telegram voice messages via the Requesty router.

Same BYOK model as chat and embeddings: the athlete's own Requesty key pays
for the transcription, so no second provider key is needed. Requesty exposes
an OpenAI-compatible POST /v1/audio/transcriptions that takes a multipart file
upload, and it accepts ogg — which is exactly what Telegram voice notes are,
so no ffmpeg transcoding is required.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from config import get_config

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(120.0)

# Requesty rejects anything larger; Telegram's own download limit is lower
# still, but a caller could hand us a file from elsewhere.
MAX_AUDIO_BYTES = 32 * 1024 * 1024

# Telegram mime type → the extension Requesty expects in the filename.
_EXTENSIONS = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/flac": "flac",
}


def _resolve_api_key(user_id: Optional[int]) -> Optional[str]:
    """The user's Requesty key, else the service-wide one, else None."""
    cfg = get_config()

    if user_id is not None:
        try:
            # Lazy import keeps this module importable without the DB layer.
            from db.client import get_db
            from utils.crypto import decrypt

            row = (
                get_db()
                .table("users")
                .select("llm_api_key_enc")
                .eq("id", user_id)
                .single()
                .execute()
            ).data
            if row and row.get("llm_api_key_enc"):
                return decrypt(row["llm_api_key_enc"])
        except Exception as exc:
            logger.warning("Could not load Requesty key for user %s: %s", user_id, exc)

    return cfg.requesty_api_key or None


def filename_for(mime_type: Optional[str]) -> str:
    """Requesty picks the decoder from the extension, so it must be right."""
    return f"voice.{_EXTENSIONS.get((mime_type or '').lower(), 'ogg')}"


async def transcribe(
    audio_bytes: bytes,
    user_id: Optional[int] = None,
    mime_type: Optional[str] = None,
    language: str = "de",
) -> Optional[str]:
    """
    Transcribe an audio clip. Returns the text, or None when it failed.

    None means "tell the athlete it didn't work" – never fall back to an empty
    string, or the agent would be handed a message with no content.
    """
    if not audio_bytes:
        return None
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        logger.warning("Audio too large: %d bytes", len(audio_bytes))
        return None

    api_key = _resolve_api_key(user_id)
    if not api_key:
        logger.warning("No Requesty key for user %s – cannot transcribe", user_id)
        return None

    cfg = get_config()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{cfg.requesty_base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (filename_for(mime_type), audio_bytes, mime_type or "audio/ogg")},
                data={"model": cfg.transcription_model, "language": language},
            )
            resp.raise_for_status()
            text = (resp.json().get("text") or "").strip()
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        return None

    return text or None
