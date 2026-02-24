from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class HeritageSite(Base):
    __tablename__ = "heritage_sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geofence_radius_meters = Column(Integer, nullable=False)

    summary = Column(Text)
    history = Column(Text)
    fun_facts = Column(Text)

    helpline_number = Column(String)
    static_map_url = Column(String)
    intro_video_url = Column(String)

    rating = Column(Float, default=4.5)
    upvotes = Column(Integer, default=100)

    images = relationship("SiteImage", back_populates="site")
    nodes = relationship("Node", back_populates="site")


class SiteImage(Base):
    __tablename__ = "site_images"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("heritage_sites.id"))
    image_url = Column(String)
    display_order = Column(Integer)

    site = relationship("HeritageSite", back_populates="images")


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("heritage_sites.id"))

    name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    sequence_order = Column(Integer)

    qr_code_value = Column(String, unique=True)

    description = Column(Text)
    image_url = Column(String)

    site = relationship("HeritageSite", back_populates="nodes")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    site_id = Column(Integer)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer)
    type = Column(String)  # hotel, restaurant, nearby
    name = Column(String)
    description = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, nullable=True)
    node_id = Column(Integer, nullable=True)
    context_prompt_text = Column(Text)