# app/models.py

from pydantic import BaseModel
from typing import List


class Message(BaseModel):
    role: str       # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[Message] = []
    site_name: str = ""
    site_id: str = ""


class ChatResponse(BaseModel):
    reply: str


class VoiceChatResponse(BaseModel):
    user_text:    str
    bot_text:     str
    audio_base64: str
    audio_format: str = "wav"
