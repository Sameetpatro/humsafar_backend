# app/schemas.py
# FIXED:
#   NodeResponse now includes `description` and `video_url` so that
#   NodeDetailScreen can display node-specific content.
#   Previously these were missing → Android NodeDetail always showed blank sections.

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


# ── Chat ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    str
    content: str


class ChatRequest(BaseModel):
    site_id: int
    node_id: Optional[int] = None
    message: str
    history: List[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str


# ── Voice ─────────────────────────────────────────────────────────────────────

class VoiceChatResponse(BaseModel):
    user_text:    str
    bot_text:     str
    audio_base64: str
    audio_format: str


# ── Site Listing ──────────────────────────────────────────────────────────────

class NearbySiteResponse(BaseModel):
    id:              int
    name:            str
    distance_meters: float
    inside_geofence: bool


class SiteImageResponse(BaseModel):
    id:            int
    image_url:     str
    display_order: int

    class Config:
        from_attributes = True


class NodeResponse(BaseModel):
    id:             int
    name:           str
    latitude:       float
    longitude:      float
    sequence_order: int
    is_king:        bool = False
    # FIXED: these were missing — Android NodeDetailScreen reads both fields
    description:    Optional[str] = None
    video_url:      Optional[str] = None

    class Config:
        from_attributes = True


class SiteDetailResponse(BaseModel):
    id:                     int
    name:                   str
    latitude:               float
    longitude:              float
    geofence_radius_meters: int
    summary:                Optional[str] = None
    history:                Optional[str] = None
    fun_facts:              Optional[str] = None
    helpline_number:        Optional[str] = None
    static_map_url:         Optional[str] = None
    intro_video_url:        Optional[str] = None
    rating:                 float
    upvotes:                int
    images:                 List[SiteImageResponse] = []
    nodes:                  List[NodeResponse] = []

    class Config:
        from_attributes = True


# ── Trip ──────────────────────────────────────────────────────────────────────

class StartTripRequest(BaseModel):
    user_id:  str   # FIXED: was int — guest_user_001 needs str
    qr_value: str


class StartTripResponse(BaseModel):
    message: str
    trip_id: int


class EndTripRequest(BaseModel):
    trip_id: int


class EndTripResponse(BaseModel):
    message: str


# ── Recommendation ────────────────────────────────────────────────────────────

class RecommendationResponse(BaseModel):
    id:          int
    type:        str
    name:        str
    description: Optional[str] = None
    latitude:    Optional[float] = None
    longitude:   Optional[float] = None