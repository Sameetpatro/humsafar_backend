
# app/services/voice_orchestrator.py
# NEW FILE

import base64
import logging
from dataclasses import dataclass

from app.services.sarvam_stt import transcribe
from app.services.sarvam_tts import synthesize
from app.services             import call_openrouter

logger = logging.getLogger(__name__)

# Per-language instruction injected into the LLM system prompt.
# STT stage already handles transcription in the target language.
# This controls the *response* style.
_LANG_INSTRUCTIONS: dict[str, str] = {
    "ENGLISH": (
        "Respond in clear, natural English."
    ),
    "HINDI": (
        "Respond only in Hindi using Devanagari script. "
        "Use formal but accessible language."
    ),
    "HINGLISH": (
        "Respond in Hinglish — a natural mix of Hindi and English "
        "as spoken by urban Indians. Use Roman script for Hindi words. "
        "Example: 'Yeh fort bahut historic hai aur iska architecture amazing hai.' "
        "Keep it conversational and friendly."
    ),
}


@dataclass
class PipelineResult:
    user_text:    str
    bot_text:     str
    audio_bytes:  bytes
    audio_base64: str


async def run(
    audio_bytes:   bytes,
    site_name:     str,
    site_id:       str,
    language_code: str,   # BCP-47 e.g. "en-IN"
    lang_name:     str,   # "ENGLISH" | "HINDI" | "HINGLISH"
) -> PipelineResult:
    """
    Executes the full voice pipeline sequentially:
      STT → LLM → TTS

    Each stage raises RuntimeError with a stage-prefixed message on failure.
    The router wraps these in structured HTTPException responses.

    Pipeline is inherently sequential:
      STT output feeds LLM → LLM output feeds TTS → no parallelism possible.
    """

    # ── Stage 1: STT ─────────────────────────────────────────────────────
    logger.info(f"[Pipeline] STT start — {len(audio_bytes)} bytes, lang={language_code}")
    try:
        user_text = await transcribe(audio_bytes, language_code)
    except Exception as exc:
        raise RuntimeError(f"STT_FAILED: {exc}") from exc

    # ── Stage 2: LLM ─────────────────────────────────────────────────────
    lang_instruction = _LANG_INSTRUCTIONS.get(lang_name, _LANG_INSTRUCTIONS["ENGLISH"])
    system_prompt = f"""You are HUMSAFAR, an intelligent AI heritage guide.
The visitor is currently at: {site_name}

Language instruction: {lang_instruction}

Guidelines:
- Answer questions about this heritage site accurately and engagingly.
- Mention architecture, history, notable legends, and visiting tips when relevant.
- Keep responses concise (2–4 sentences) — this is a voice interface, not a text essay.
- Do not use markdown formatting (no asterisks, bullets, headers).
- Do not hallucinate facts you are not confident about."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_text},
    ]

    logger.info(f"[Pipeline] LLM start — userText='{user_text[:60]}'")
    try:
        bot_text = await call_openrouter(messages)
    except Exception as exc:
        raise RuntimeError(f"LLM_FAILED: {exc}") from exc

    logger.info(f"[Pipeline] LLM done — botText='{bot_text[:60]}'")

    # ── Stage 3: TTS ─────────────────────────────────────────────────────
    logger.info(f"[Pipeline] TTS start — {len(bot_text)} chars")
    try:
        audio_bytes_out = await synthesize(bot_text, language_code)
    except Exception as exc:
        raise RuntimeError(f"TTS_FAILED: {exc}") from exc

    audio_b64 = base64.b64encode(audio_bytes_out).decode()
    logger.info(
        f"[Pipeline] Complete — "
        f"STT={len(user_text)}c LLM={len(bot_text)}c TTS={len(audio_bytes_out)}B"
    )

    return PipelineResult(
        user_text    = user_text,
        bot_text     = bot_text,
        audio_bytes  = audio_bytes_out,
        audio_base64 = audio_b64,
    )