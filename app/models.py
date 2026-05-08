# app/models.py
# UPGRADED: Full Dharohar Setu schema v2
#   - Added User model with UUID PK + firebase_uid
#   - All user_id columns now reference users.id (UUID FK)
#   - Added NodeRating, NodeComment, SiteFeedback tables
#   - Added image_type, width, height to SiteImage and NodeImage
#   - Added avg_rating, rating_count to Node
#   - Added entry_lat, entry_lng to Trip
#   - Removed dependency on db_triggers.py (ratings updated transactionally in routers)

import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    Text,
    DateTime,
    Index,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


# ── Users ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid   = Column(String(128), unique=True, nullable=False)
    display_name   = Column(String(255), nullable=True)
    email          = Column(String(255), nullable=True)
    phone          = Column(String(20), nullable=True)
    avatar_url     = Column(Text, nullable=True)
    preferred_lang = Column(String(10), default="en-IN")
    is_anonymous   = Column(Boolean, default=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── Heritage Sites ────────────────────────────────────────────────────────────

class HeritageSite(Base):
    __tablename__ = "heritage_sites"

    id                     = Column(Integer, primary_key=True, index=True)
    name                   = Column(String(255), nullable=False)
    latitude               = Column(Float, nullable=False)
    longitude              = Column(Float, nullable=False)
    geofence_radius_meters = Column(Integer, default=100)
    summary                = Column(Text)
    history                = Column(Text)
    fun_facts              = Column(Text)
    helpline_number        = Column(String(50))
    static_map_url         = Column(Text)
    intro_video_url        = Column(Text)
    rating                 = Column(Float, default=0.0)   # denormalized avg — updated transactionally
    upvotes                = Column(Integer, default=0)
    created_at             = Column(DateTime(timezone=True), server_default=func.now())

    images = relationship("SiteImage", back_populates="site", order_by="SiteImage.display_order",  cascade="all, delete-orphan")
    nodes  = relationship("Node",      back_populates="site", order_by="Node.sequence_order",       cascade="all, delete-orphan")
    trips  = relationship("Trip",      back_populates="site",                                       cascade="all, delete-orphan")


class SiteImage(Base):
    __tablename__ = "site_images"

    id            = Column(Integer, primary_key=True, index=True)
    site_id       = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    image_url     = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    image_type    = Column(String(20), default="gallery")   # gallery | hero | thumbnail
    width         = Column(Integer, nullable=True)
    height        = Column(Integer, nullable=True)

    site = relationship("HeritageSite", back_populates="images")


# ── Nodes ─────────────────────────────────────────────────────────────────────

class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        # Hard guarantee at the DB layer: exactly ONE king node per site.
        # Application layer (admin/seed-bulk) also enforces this, but a partial
        # unique index protects against direct DB inserts / future endpoints.
        Index(
            "uq_king_node_per_site",
            "site_id",
            unique=True,
            postgresql_where=text("is_king = TRUE"),
        ),
    )

    id             = Column(Integer, primary_key=True, index=True)
    site_id        = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    name           = Column(String(255), nullable=False)
    latitude       = Column(Float, nullable=False)
    longitude      = Column(Float, nullable=False)
    sequence_order = Column(Integer, default=0)
    is_king        = Column(Boolean, default=False)
    description    = Column(Text)
    video_url      = Column(String)
    image_url      = Column(String)                         # legacy single image — kept for compat
    qr_code_value  = Column(String(255), unique=True, nullable=False)
    avg_rating     = Column(Float, default=0.0)             # denormalized — updated transactionally
    rating_count   = Column(Integer, default=0)

    site   = relationship("HeritageSite", back_populates="nodes")
    images = relationship("NodeImage", back_populates="node", order_by="NodeImage.display_order", cascade="all, delete-orphan")


class NodeImage(Base):
    __tablename__ = "node_images"

    id            = Column(Integer, primary_key=True, index=True)
    node_id       = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    image_url     = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    image_type    = Column(String(20), default="gallery")   # gallery | hero | thumbnail
    width         = Column(Integer, nullable=True)
    height        = Column(Integer, nullable=True)

    node = relationship("Node", back_populates="images")


# ── Trips ─────────────────────────────────────────────────────────────────────

class Trip(Base):
    __tablename__ = "trips"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    site_id    = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at   = Column(DateTime(timezone=True), nullable=True)
    is_active  = Column(Boolean, default=True)
    entry_lat  = Column(Float, nullable=True)
    entry_lng  = Column(Float, nullable=True)

    site = relationship("HeritageSite", back_populates="trips")


# ── Visit History ─────────────────────────────────────────────────────────────

class UserVisitHistory(Base):
    __tablename__ = "user_visit_history"
    __table_args__ = (UniqueConstraint("user_id", "trip_id", name="uq_user_visit_user_trip"),)

    id               = Column(Integer, primary_key=True, index=True)
    user_id          = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    site_id          = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    trip_id          = Column(Integer, ForeignKey("trips.id", ondelete="SET NULL"), nullable=True)
    site_name        = Column(String(255), nullable=False)
    nodes_visited    = Column(ARRAY(Integer), server_default=text("'{}'"), default=lambda: [])
    total_nodes      = Column(Integer, default=0)
    nodes_completed  = Column(Integer, default=0)
    completed        = Column(Boolean, default=True)
    visited_at       = Column(DateTime(timezone=True), nullable=False)
    ended_at         = Column(DateTime(timezone=True), nullable=True)
    duration_mins    = Column(Integer, nullable=True)
    entry_lat        = Column(Float, nullable=True)
    entry_lng        = Column(Float, nullable=True)
    review_submitted = Column(Boolean, default=False)


# ── Ratings & Reviews ─────────────────────────────────────────────────────────

class SiteRating(Base):
    __tablename__ = "site_ratings"
    __table_args__ = (UniqueConstraint("site_id", "user_id", name="uq_site_ratings_site_user"),)

    id         = Column(Integer, primary_key=True, index=True)
    site_id    = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating     = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class NodeRating(Base):
    """Per-user per-node star rating. New table — not in original schema."""
    __tablename__ = "node_ratings"
    __table_args__ = (UniqueConstraint("node_id", "user_id", name="uq_node_ratings_node_user"),)

    id         = Column(Integer, primary_key=True, index=True)
    node_id    = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    site_id    = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating     = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class TripReview(Base):
    __tablename__ = "trip_reviews"
    __table_args__ = (UniqueConstraint("trip_id", name="uq_trip_reviews_trip"),)

    id                     = Column(Integer, primary_key=True, index=True)
    trip_id                = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    site_id                = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    user_id                = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    q1_overall_experience  = Column(SmallInteger, nullable=False)
    q2_guide_helpfulness   = Column(SmallInteger, nullable=False)
    q3_recommend_to_others = Column(SmallInteger, nullable=False)
    suggestion_text        = Column(Text, nullable=True)
    submitted_at           = Column(DateTime(timezone=True), server_default=func.now())


class AnalyzedResponse(Base):
    """Materialized analytics per site. Refreshed by background worker, never by trigger."""
    __tablename__ = "analyzed_responses"
    __table_args__ = (UniqueConstraint("site_id", name="uq_analyzed_responses_site"),)

    id                     = Column(Integer, primary_key=True, index=True)
    site_id                = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False, unique=True)
    avg_star_rating        = Column(Float, default=0.0)
    total_ratings          = Column(Integer, default=0)
    avg_overall_experience = Column(Float, default=0.0)
    avg_guide_helpfulness  = Column(Float, default=0.0)
    avg_recommend_score    = Column(Float, default=0.0)
    total_reviews          = Column(Integer, default=0)
    recommend_pct          = Column(Float, default=0.0)
    satisfaction_label     = Column(String(50), default="No data")
    last_updated           = Column(DateTime(timezone=True), server_default=func.now())


# ── AI & Content ──────────────────────────────────────────────────────────────

class Prompt(Base):
    __tablename__ = "prompts"

    id      = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("heritage_sites.id"), nullable=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=True)
    title   = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)

    site = relationship("HeritageSite")
    node = relationship("Node")


class UserChatHistory(Base):
    """Every chat message per user per trip. Fastest growing table — partition by month at 10M rows."""
    __tablename__ = "user_chat_history"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    trip_id    = Column(Integer, ForeignKey("trips.id", ondelete="SET NULL"), nullable=True)
    site_id    = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    node_id    = Column(Integer, ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    role       = Column(String(20), nullable=False)         # 'user' | 'assistant'
    content    = Column(Text, nullable=False)
    lang_code  = Column(String(10), default="en-IN")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# ── Community ─────────────────────────────────────────────────────────────────

class NodeComment(Base):
    """User comments on individual nodes. Future release feature."""
    __tablename__ = "node_comments"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    site_id    = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    node_id    = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    content    = Column(Text, nullable=False)
    is_flagged = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class SiteFeedback(Base):
    """General feedback. Supports anonymous submissions (user_id nullable)."""
    __tablename__ = "site_feedback"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    site_id    = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    category   = Column(String(50), default="general")      # general | accessibility | content | bug
    content    = Column(Text, nullable=False)
    status     = Column(String(30), default="open")         # open | reviewed | resolved
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Discovery ─────────────────────────────────────────────────────────────────

class Recommendation(Base):
    __tablename__ = "recommendations"

    id          = Column(Integer, primary_key=True, index=True)
    site_id     = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    type        = Column(String(50), nullable=False)        # monument | hotel | restaurant | activity
    name        = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    latitude    = Column(Float, nullable=True)
    longitude   = Column(Float, nullable=True)

    site = relationship("HeritageSite")


class Amenity(Base):
    __tablename__ = "amenities"

    id          = Column(Integer, primary_key=True, index=True)
    site_id     = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    node_id     = Column(Integer, ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True)
    type        = Column(String(50), nullable=False)        # washroom | shop | first_aid | parking
    name        = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    latitude    = Column(Float, nullable=False)
    longitude   = Column(Float, nullable=False)
    price_info  = Column(String(255), nullable=True)
    timing      = Column(String(255), nullable=True)
    is_paid     = Column(Boolean, default=False)

    site = relationship("HeritageSite")
    node = relationship("Node")