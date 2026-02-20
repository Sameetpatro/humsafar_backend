# app/models.py  ← REPLACES EXISTING FILE
# CHANGES: + VoiceChatResponse, VoicePipelineError

from pydantic import BaseModel
from typing import List, Dict, Optional


# ── Existing (unchanged) ──────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:   str
    site_name: str
    site_id:   str
    history:   List[Dict[str, str]] = []


class ChatResponse(BaseModel):
    reply: str


# ── Voice pipeline ────────────────────────────────────────────────────────────

class VoiceChatResponse(BaseModel):
    """
    Returned by POST /voice-chat.
    audio_base64 is a base64-encoded WAV produced by Sarvam TTS.
    """
    user_text:    str
    bot_text:     str
    audio_base64: str
    audio_format: str = "wav"


class VoicePipelineError(BaseModel):
    """Structured error for partial pipeline failures."""
    stage:   str            # "stt" | "llm" | "tts"
    message: str
    detail:  Optional[str] = None