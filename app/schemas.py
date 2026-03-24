# app/schemas.py

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
    is_king:        bool         = False
    description:    Optional[str] = None
    video_url:      Optional[str] = None
    image_url:      Optional[str] = None
    images:         List[NodeImageResponse] = []
    qr_code_value: str
    class Config:
        from_attributes = True

class NodePositionResponse(BaseModel):
    id:             int
    name:           str
    latitude:       float
    longitude:      float
    sequence_order: int
    is_king:        bool = False
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
    nodes:                  List[NodeResponse]      = []
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

class RecommendationResponse(BaseModel):
    id:          int
    site_id:     int
    type:        str
    name:        str
    description: Optional[str]   = None
    latitude:    Optional[float]  = None
    longitude:   Optional[float]  = None
    class Config:
        from_attributes = True

# ── Amenity ───────────────────────────────────────────────────────────────────

class AmenityResponse(BaseModel):
    id:              int
    site_id:         int
    node_id:         Optional[int]   = None
    type:            str
    name:            str
    description:     Optional[str]   = None
    latitude:        float
    longitude:       float
    price_info:      Optional[str]   = None
    timing:          Optional[str]   = None
    is_paid:         bool            = False
    distance_meters: Optional[float] = None
    class Config:
        from_attributes = True