# app/services/sarvam_stt.py
# NEW FILE

import os
import logging

import httpx

logger = logging.getLogger(__name__)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
STT_URL        = "https://api.sarvam.ai/speech-to-text"
STT_TIMEOUT    = 60.0   # seconds — generous for free tier


async def transcribe(
    audio_bytes:   bytes,
    language_code: str,   # BCP-47, e.g. "en-IN", "hi-IN"
) -> str:
    """
    Sends WAV bytes to Sarvam STT and returns the transcript.

    Sarvam STT request:
      POST https://api.sarvam.ai/speech-to-text
      Headers: api-subscription-key: <key>
      Body: multipart/form-data
        file          — audio/wav bytes
        language_code — BCP-47
        model         — "saarika:v1"
        with_timestamps — false

    Response: { "transcript": "...", "language_code": "en-IN", ... }

    Raises RuntimeError on API failure or empty transcript.
    """
    if not SARVAM_API_KEY:
        raise RuntimeError("SARVAM_API_KEY is not set in environment")

    logger.info(f"[STT] Sending {len(audio_bytes)} bytes, lang={language_code}")

    async with httpx.AsyncClient(timeout=STT_TIMEOUT) as client:
        response = await client.post(
            STT_URL,
            headers={"api-subscription-key": SARVAM_API_KEY},
            files={"file": ("recording.wav", audio_bytes, "audio/wav")},
            data={
                "language_code":    language_code,
                "model":            "saarika:v2.5",
                "with_timestamps":  "false",
            }
        )

    if response.status_code != 200:
        logger.error(f"[STT] {response.status_code}: {response.text}")
        raise RuntimeError(f"Sarvam STT error {response.status_code}: {response.text}")

    body       = response.json()
    transcript = body.get("transcript", "").strip()

    if not transcript:
        raise RuntimeError("Sarvam STT returned empty transcript — audio may be silent or too short")

    logger.info(f"[STT] Transcript ({len(transcript)} chars): '{transcript[:80]}'")
    return transcript