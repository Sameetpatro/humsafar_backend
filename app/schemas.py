# app/schemas.py
# UPGRADED: Added User, NodeRating, NodeComment, SiteFeedback, UserChatHistory schemas.
#   image_type/dimensions added to SiteImage and NodeImage responses.
#   user_id fields now return UUID strings.

from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from datetime import datetime


# ── Auth / Users ──────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    firebase_uid:   str
    display_name:   Optional[str] = None
    email:          Optional[str] = None
    phone:          Optional[str] = None
    avatar_url:     Optional[str] = None
    preferred_lang: str = "en-IN"
    is_anonymous:   bool = False


class UserResponse(BaseModel):
    id:             UUID
    firebase_uid:   str
    display_name:   Optional[str] = None
    email:          Optional[str] = None
    phone:          Optional[str] = None
    avatar_url:     Optional[str] = None
    preferred_lang: str
    is_anonymous:   bool
    created_at:     datetime
    last_active_at: datetime

    class Config:
        from_attributes = True


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    str
    content: str


class ChatRequest(BaseModel):
    site_id: int
    node_id: Optional[int] = None
    message: str
    history: List[ChatMessage] = []
    # Optional persistence fields. When firebase_uid is provided the user's
    # message and the assistant reply are written to user_chat_history.
    # Calls without firebase_uid still work (no DB write) — keeps backwards
    # compatibility with older Android builds.
    firebase_uid: Optional[str] = None
    trip_id:      Optional[int] = None
    lang_code:    Optional[str] = None


class ChatResponse(BaseModel):
    reply: str


# ── Voice ─────────────────────────────────────────────────────────────────────

class VoiceChatResponse(BaseModel):
    user_text:    str
    bot_text:     str
    audio_base64: str
    audio_format: str


# ── Images ────────────────────────────────────────────────────────────────────

class SiteImageResponse(BaseModel):
    id:            int
    image_url:     str
    display_order: int
    image_type:    str = "gallery"
    width:         Optional[int] = None
    height:        Optional[int] = None

    class Config:
        from_attributes = True


class NodeImageResponse(BaseModel):
    id:            int
    image_url:     str
    display_order: int
    image_type:    str = "gallery"
    width:         Optional[int] = None
    height:        Optional[int] = None

    class Config:
        from_attributes = True


# ── Sites ─────────────────────────────────────────────────────────────────────

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
    is_king:        bool           = False
    description:    Optional[str]  = None
    video_url:      Optional[str]  = None
    image_url:      Optional[str]  = None
    images:         List[NodeImageResponse] = []
    qr_code_value:  str
    avg_rating:     float          = 0.0
    rating_count:   int            = 0

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


# ── Trips ─────────────────────────────────────────────────────────────────────

class StartTripRequest(BaseModel):
    user_id:  str           # firebase_uid — resolved to UUID in router
    qr_value: str


class StartTripResponse(BaseModel):
    message: str
    trip_id: int


class EndTripRequest(BaseModel):
    trip_id: int


class EndTripResponse(BaseModel):
    message: str


# ── Ratings ───────────────────────────────────────────────────────────────────

class SiteRatingRequest(BaseModel):
    site_id:     int
    firebase_uid: str        # resolved to user UUID in router
    rating:      int         # 1–5


class SiteRatingResponse(BaseModel):
    message:    str
    new_avg:    float
    total:      int


class NodeRatingRequest(BaseModel):
    node_id:      int
    site_id:      int
    firebase_uid: str        # resolved to user UUID in router
    rating:       int        # 1–5


class NodeRatingResponse(BaseModel):
    message:   str
    new_avg:   float
    total:     int


# ── Reviews ───────────────────────────────────────────────────────────────────

class ReviewSubmitBody(BaseModel):
    trip_id:        int
    site_id:        int
    firebase_uid:   str      # resolved to user UUID in router
    star_rating:    int      # 1–5
    q1:             int
    q2:             int
    q3:             int
    suggestion_text: Optional[str] = None


class ReviewSubmitResponse(BaseModel):
    message:    str
    review_id:  int
    new_rating: float


class ReviewSummaryResponse(BaseModel):
    avg_star_rating:        float
    total_ratings:          int
    avg_overall_experience: float
    avg_guide_helpfulness:  float
    avg_recommend_score:    float
    total_reviews:          int
    recommend_pct:          float
    satisfaction_label:     str


# ── Community ─────────────────────────────────────────────────────────────────

class NodeCommentCreate(BaseModel):
    firebase_uid: str
    site_id:      int
    node_id:      int
    content:      str


class NodeCommentResponse(BaseModel):
    id:         int
    user_id:    UUID
    site_id:    int
    node_id:    int
    content:    str
    is_flagged: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SiteFeedbackCreate(BaseModel):
    firebase_uid: Optional[str] = None  # None = anonymous
    site_id:      int
    category:     str = "general"
    content:      str


class SiteFeedbackResponse(BaseModel):
    id:         int
    site_id:    int
    category:   str
    content:    str
    status:     str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Discovery ─────────────────────────────────────────────────────────────────

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