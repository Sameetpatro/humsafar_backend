# app/models.py
# FINAL STRUCTURE:
#   - HeritageSite
#   - SiteImage
#   - Node
#   - NodeImage
#   - Trip

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    Text,
    DateTime,
)
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

    # Relationships
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
    image_url      = Column(String)   # legacy single image
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
# Trip (REQUIRED for trips.py)
# ==============================

class Trip(Base):
    __tablename__ = "trips"

    id        = Column(Integer, primary_key=True, index=True)
    user_id   = Column(String, nullable=False)  # guest_user_001 etc
    site_id   = Column(Integer, ForeignKey("heritage_sites.id"), nullable=False)

    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at   = Column(DateTime(timezone=True), nullable=True)

    is_active = Column(Boolean, default=True)

    site = relationship("HeritageSite", back_populates="trips")