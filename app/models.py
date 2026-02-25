# app/models.py
# UPDATED: Added NodeImage model + Node.images relationship

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class HeritageSite(Base):
    __tablename__ = "heritage_sites"

    id                     = Column(Integer, primary_key=True, index=True)
    name                   = Column(String, nullable=False)
    latitude               = Column(Float, nullable=False)
    longitude              = Column(Float, nullable=False)
    geofence_radius_meters = Column(Integer, default=100)
    summary                = Column(Text)
    history                = Column(Text)
    fun_facts              = Column(Text)
    helpline_number        = Column(String)
    static_map_url         = Column(String)
    intro_video_url        = Column(String)   # ← video for HeritageDetailScreen
    rating                 = Column(Float, default=0.0)
    upvotes                = Column(Integer, default=0)

    images = relationship("SiteImage", back_populates="site",
                          order_by="SiteImage.display_order")
    nodes  = relationship("Node", back_populates="site",
                          order_by="Node.sequence_order")


class SiteImage(Base):
    __tablename__ = "site_images"

    id            = Column(Integer, primary_key=True, index=True)
    site_id       = Column(Integer, ForeignKey("heritage_sites.id"), nullable=False)
    image_url     = Column(String, nullable=False)
    display_order = Column(Integer, default=0)

    site = relationship("HeritageSite", back_populates="images")


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
    video_url      = Column(String)   # ← video for NodeDetailScreen
    image_url      = Column(String)   # legacy single image
    qr_code_value  = Column(String, unique=True)

    site   = relationship("HeritageSite", back_populates="nodes")
    images = relationship("NodeImage", back_populates="node",
                          order_by="NodeImage.display_order")  # ← NEW


class NodeImage(Base):
    """node_images table — multiple images per node, sorted by display_order"""
    __tablename__ = "node_images"

    id            = Column(Integer, primary_key=True, index=True)
    node_id       = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    image_url     = Column(String, nullable=False)
    display_order = Column(Integer, default=0)

    node = relationship("Node", back_populates="images")