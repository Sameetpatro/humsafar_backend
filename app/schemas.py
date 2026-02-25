# app/schemas.py
# UPDATED: NodeResponse now includes images: List[NodeImageResponse]

from pydantic import BaseModel
from typing import List, Optional


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

class VoiceChatResponse(BaseModel):
    user_text:    str
    bot_text:     str
    audio_base64: str
    audio_format: str

class SiteImageResponse(BaseModel):
    id:            int
    image_url:     str
    display_order: int
    class Config:
        from_attributes = True

# NEW ─────────────────────────────────────────────────────────────────────────
class NodeImageResponse(BaseModel):
    id:            int
    image_url:     str
    display_order: int
    class Config:
        from_attributes = True

class NearbySiteResponse(BaseModel):
    id:              int
    name:            str
    latitude:        float
    longitude:       float
    distance_meters: float
    inside_geofence: bool

class NodeResponse(BaseModel):
    id:             int
    name:           str
    latitude:       float
    longitude:      float
    sequence_order: int
    is_king:        bool = False
    description:    Optional[str] = None
    video_url:      Optional[str] = None
    image_url:      Optional[str] = None
    images:         List[NodeImageResponse] = []   # ← node_images rows
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
    intro_video_url:        Optional[str] = None   # ← heritage_sites.intro_video_url
    rating:                 float
    upvotes:                int
    images:                 List[SiteImageResponse] = []
    nodes:                  List[NodeResponse] = []
    class Config:
        from_attributes = True

class StartTripRequest(BaseModel):
    user_id:  str
    qr_value: str

class StartTripResponse(BaseModel):
    message: str
    trip_id: int

class EndTripRequest(BaseModel):
    trip_id: int

class EndTripResponse(BaseModel):
    message: str