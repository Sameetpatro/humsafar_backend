# app/models.py
# Tables created by Base.metadata.create_all() — same pattern as heritage_sites, trips, etc.

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    Text,
    DateTime,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


# ==============================
# Heritage Site
# ==============================

class HeritageSite(Base):
    __tablename__ = "heritage_sites"

    id                     = Column(Integer, primary_key=True, index=True)
    name                   = Column(String, nullable=False)
    latitude               = Column(Float, nullable=False)
    longitude              = Column(Float, nullable=False)
    geofence_radius_meters = Column(Integer, default=100)

    summary         = Column(Text)
    history         = Column(Text)
    fun_facts       = Column(Text)
    helpline_number = Column(String)

    static_map_url  = Column(String)
    intro_video_url = Column(String)

    rating  = Column(Float, default=0.0)
    upvotes = Column(Integer, default=0)

    images = relationship(
        "SiteImage",
        back_populates="site",
        order_by="SiteImage.display_order",
        cascade="all, delete-orphan"
    )
    nodes = relationship(
        "Node",
        back_populates="site",
        order_by="Node.sequence_order",
        cascade="all, delete-orphan"
    )
    trips = relationship(
        "Trip",
        back_populates="site",
        cascade="all, delete-orphan"
    )


# ==============================
# Site Images
# ==============================

class SiteImage(Base):
    __tablename__ = "site_images"

    id            = Column(Integer, primary_key=True, index=True)
    site_id       = Column(Integer, ForeignKey("heritage_sites.id"), nullable=False)
    image_url     = Column(String, nullable=False)
    display_order = Column(Integer, default=0)

    site = relationship("HeritageSite", back_populates="images")


# ==============================
# Node
# ==============================

class Node(Base):
    __tablename__ = "nodes"

    id             = Column(Integer, primary_key=True, index=True)
    site_id        = Column(Integer, ForeignKey("heritage_sites.id"), nullable=False)
    name           = Column(String, nullable=False)
    latitude       = Column(Float, nullable=False)
    longitude      = Column(Float, nullable=False)
    sequence_order = Column(Integer, default=0)
    is_king        = Column(Boolean, default=False)
    description    = Column(Text)
    video_url      = Column(String)
    image_url      = Column(String)
    qr_code_value  = Column(String, unique=True)

    site = relationship("HeritageSite", back_populates="nodes")
    images = relationship(
        "NodeImage",
        back_populates="node",
        order_by="NodeImage.display_order",
        cascade="all, delete-orphan"
    )


# ==============================
# Node Images
# ==============================

class NodeImage(Base):
    __tablename__ = "node_images"

    id            = Column(Integer, primary_key=True, index=True)
    node_id       = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    image_url     = Column(String, nullable=False)
    display_order = Column(Integer, default=0)

    node = relationship("Node", back_populates="images")


# ==============================
# Trip
# ==============================

class Trip(Base):
    __tablename__ = "trips"

    id        = Column(Integer, primary_key=True, index=True)
    user_id   = Column(String, nullable=False)
    site_id   = Column(Integer, ForeignKey("heritage_sites.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at   = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)

    site = relationship("HeritageSite", back_populates="trips")


class Prompt(Base):
    __tablename__ = "prompts"

    id       = Column(Integer, primary_key=True, index=True)
    site_id  = Column(Integer, ForeignKey("heritage_sites.id"), nullable=True)
    node_id  = Column(Integer, ForeignKey("nodes.id"), nullable=True)
    title    = Column(String, nullable=False)
    content  = Column(Text, nullable=False)

    site = relationship("HeritageSite")
    node = relationship("Node")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id          = Column(Integer, primary_key=True, index=True)
    site_id     = Column(Integer, ForeignKey("heritage_sites.id"), nullable=False)
    type        = Column(String, nullable=False)
    name        = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    latitude    = Column(Float, nullable=True)
    longitude   = Column(Float, nullable=True)

    site = relationship("HeritageSite")


# ==============================
# Reviews & Visit History (create_all creates these tables)
# ==============================

class SiteRating(Base):
    __tablename__ = "site_ratings"
    __table_args__ = (UniqueConstraint("site_id", "user_id", name="uq_site_ratings_site_user"),)

    id         = Column(Integer, primary_key=True, index=True)
    site_id    = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(String, nullable=False)
    rating     = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class TripReview(Base):
    __tablename__ = "trip_reviews"
    __table_args__ = (UniqueConstraint("trip_id", name="uq_trip_reviews_trip"),)

    id                      = Column(Integer, primary_key=True, index=True)
    trip_id                 = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    site_id                 = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    user_id                 = Column(String, nullable=False)
    q1_overall_experience   = Column(SmallInteger, nullable=False)
    q2_guide_helpfulness    = Column(SmallInteger, nullable=False)
    q3_recommend_to_others  = Column(SmallInteger, nullable=False)
    suggestion_text         = Column(Text, nullable=True)
    submitted_at            = Column(DateTime(timezone=True), server_default=func.now())


class AnalyzedResponse(Base):
    __tablename__ = "analyzed_responses"
    __table_args__ = (UniqueConstraint("site_id", name="uq_analyzed_responses_site"),)

    id                      = Column(Integer, primary_key=True, index=True)
    site_id                 = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False, unique=True)
    avg_star_rating         = Column(Float, default=0.0)
    total_ratings           = Column(Integer, default=0)
    avg_overall_experience  = Column(Float, default=0.0)
    avg_guide_helpfulness   = Column(Float, default=0.0)
    avg_recommend_score     = Column(Float, default=0.0)
    total_reviews           = Column(Integer, default=0)
    recommend_pct           = Column(Float, default=0.0)
    satisfaction_label      = Column(String, default="No data")
    last_updated            = Column(DateTime(timezone=True), server_default=func.now())


class UserVisitHistory(Base):
    __tablename__ = "user_visit_history"
    __table_args__ = (UniqueConstraint("user_id", "trip_id", name="uq_user_visit_user_trip"),)

    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(String, nullable=False)
    site_id           = Column(Integer, ForeignKey("heritage_sites.id", ondelete="CASCADE"), nullable=False)
    trip_id           = Column(Integer, ForeignKey("trips.id", ondelete="SET NULL"), nullable=True)
    site_name         = Column(String, nullable=False)
    nodes_visited     = Column(ARRAY(Integer), server_default=text("'{}'"), default=lambda: [])
    total_nodes       = Column(Integer, default=0)
    nodes_completed   = Column(Integer, default=0)
    completed         = Column(Boolean, default=True)
    visited_at        = Column(DateTime(timezone=True), nullable=False)
    ended_at          = Column(DateTime(timezone=True), nullable=True)
    duration_mins     = Column(Integer, nullable=True)
    entry_lat         = Column(Float, nullable=True)
    entry_lng         = Column(Float, nullable=True)
    review_submitted  = Column(Boolean, default=False)
