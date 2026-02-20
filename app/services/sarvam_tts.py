# app/services/sarvam_tts.py

import os
import base64
import logging
import httpx

logger = logging.getLogger(__name__)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
TTS_URL        = "https://api.sarvam.ai/text-to-speech"
TTS_TIMEOUT    = 30.0
MAX_TTS_CHARS  = 500

TTS_MODEL      = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
TTS_SPEAKER    = os.getenv("SARVAM_TTS_SPEAKER", "anushka")


async def synthesize(
    text: str,
    language_code: str,
    speaker: str | None = None,
) -> bytes:

    if not SARVAM_API_KEY:
        raise RuntimeError("SARVAM_API_KEY is not set in environment")

    if len(text) > MAX_TTS_CHARS:
        text = text[:MAX_TTS_CHARS].rsplit(" ", 1)[0] + "…"
        logger.warning(f"[TTS] Text truncated to {len(text)} chars")

    speaker = speaker or TTS_SPEAKER

    logger.info(f"[TTS] Synthesizing {len(text)} chars, lang={language_code}, speaker={speaker}, model={TTS_MODEL}")

    payload = {
        "inputs":               [text],
        "target_language_code": language_code,
        "speaker":              speaker,
        "model":                TTS_MODEL,
    }

    # Only include advanced params if NOT using bulbul:v3
    if TTS_MODEL != "bulbul:v3":
        payload.update({
            "pitch": 0,
            "pace": 1.05,
            "loudness": 1.5,
            "speech_sample_rate": 16000,
            "enable_preprocessing": True,
        })

    async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
        response = await client.post(
            TTS_URL,
            headers={
                "api-subscription-key": SARVAM_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
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