# app/services/sarvam_tts.py
# NEW FILE

import os
import base64
import logging

import httpx

logger = logging.getLogger(__name__)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
TTS_URL        = "https://api.sarvam.ai/text-to-speech"
TTS_TIMEOUT    = 30.0

# Sarvam TTS: max ~500 chars per call. Truncate with ellipsis if LLM is verbose.
MAX_TTS_CHARS  = 500


async def synthesize(
    text:          str,
    language_code: str,   # BCP-47
    speaker:       str = "anushka",  # default
) -> bytes:
    """
    Converts text to speech via Sarvam TTS. Returns raw WAV bytes.

    Sarvam TTS request:
      POST https://api.sarvam.ai/text-to-speech
      Headers: api-subscription-key: <key>, Content-Type: application/json
      Body:
        inputs               — list[str] (we send one element)
        target_language_code — BCP-47
        speaker              — "anushka" | "pavithra" | "arvind" | "amol" etc.
        pitch                — 0
        pace                 — 1.05  (slightly faster — better UX for voice assistants)
        loudness             — 1.5
        speech_sample_rate   — 16000
        enable_preprocessing — true
        model                — "bulbul:v1"

    Response: { "audios": ["<base64 wav>", ...] }

    Raises RuntimeError on failure or empty audio.
    """
    if not SARVAM_API_KEY:
        raise RuntimeError("SARVAM_API_KEY is not set in environment")

    # Truncate to API limit; don't leave the sentence mid-word
    if len(text) > MAX_TTS_CHARS:
        text = text[:MAX_TTS_CHARS].rsplit(" ", 1)[0] + "…"
        logger.warning(f"[TTS] Text truncated to {len(text)} chars")

    logger.info(f"[TTS] Synthesizing {len(text)} chars, lang={language_code}, speaker={speaker}")

    async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
        response = await client.post(
            TTS_URL,
            headers={
                "api-subscription-key": SARVAM_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "inputs":               [text],
                "target_language_code": language_code,
                "speaker":              speaker,
                "pitch":                0,
                "pace":                 1.05,
                "loudness":             1.5,
                "speech_sample_rate":   16000,
                "enable_preprocessing": True,
                "model":                "bulbul:v3",
            }
        )

    if response.status_code != 200:
        logger.error(f"[TTS] {response.status_code}: {response.text}")
        raise RuntimeError(f"Sarvam TTS error {response.status_code}: {response.text}")

    audios = response.json().get("audios", [])
    if not audios:
        raise RuntimeError("Sarvam TTS returned empty audio list")

    wav_bytes = base64.b64decode(audios[0])
    logger.info(f"[TTS] Synthesized {len(wav_bytes)} bytes")
    return wav_bytes