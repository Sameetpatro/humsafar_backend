# app/routers/admin.py
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import HeritageSite, SiteImage, Node, NodeImage, Recommendation, Prompt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


class SitePayload(BaseModel):
    name: str
    latitude: float
    longitude: float
    radius: int
    rating: Optional[float] = None
    helpline: Optional[str] = None
    video_url: Optional[str] = None
    summary: Optional[str] = None
    history: Optional[str] = None
    fun_facts: Optional[str] = None
    images: List[str] = []

class NodePayload(BaseModel):
    name: str
    latitude: float
    longitude: float
    video_url: Optional[str] = None
    sequence: int
    qr: str
    description: Optional[str] = None
    images: List[str] = []

class LandmarkPayload(BaseModel):
    name: str
    latitude: float
    longitude: float

class LandmarksPayload(BaseModel):
    monuments: List[LandmarkPayload] = []
    restaurants: List[LandmarkPayload] = []
    hotels: List[LandmarkPayload] = []

class SeedBulkRequest(BaseModel):
    site: SitePayload
    nodes: List[NodePayload]
    landmarks: Optional[LandmarksPayload] = None

class SeedPromptRequest(BaseModel):
    site_id:     int
    node_id:     Optional[int] = None
    prompt_text: str


@router.post("/seed-bulk")
def seed_bulk(payload: SeedBulkRequest, db: Session = Depends(get_db)):
    site = HeritageSite(
        name=payload.site.name,
        latitude=payload.site.latitude,
        longitude=payload.site.longitude,
        geofence_radius_meters=payload.site.radius,
        rating=payload.site.rating or 4.5,
        helpline_number=payload.site.helpline,
        intro_video_url=payload.site.video_url,
        summary=payload.site.summary,
        history=payload.site.history,
        fun_facts=payload.site.fun_facts,
    )
    db.add(site)
    db.flush()

    for order, url in enumerate(payload.site.images):
        if url:
            db.add(SiteImage(site_id=site.id, image_url=url, display_order=order))

    for node_data in payload.nodes:
        node = Node(
            site_id=site.id,
            name=node_data.name,
            latitude=node_data.latitude,
            longitude=node_data.longitude,
            sequence_order=node_data.sequence,
            qr_code_value=node_data.qr,
            description=node_data.description,
            video_url=node_data.video_url,
        )
        db.add(node)
        db.flush()
        for order, url in enumerate(node_data.images):
            if url:
                db.add(NodeImage(node_id=node.id, image_url=url, display_order=order))

    if payload.landmarks:
        for ltype, items in {"monument": payload.landmarks.monuments, "restaurant": payload.landmarks.restaurants, "hotel": payload.landmarks.hotels}.items():
            for item in items:
                if item.name:
                    db.add(Recommendation(site_id=site.id, type=ltype, name=item.name, latitude=item.latitude, longitude=item.longitude))

    db.commit()
    logger.info(f"[seed-bulk] Created site '{site.name}' id={site.id}")
    return {"success": True, "site_id": site.id, "site_name": site.name, "nodes_created": len(payload.nodes)}


@router.post("/seed-prompt")
def seed_prompt(payload: SeedPromptRequest, db: Session = Depends(get_db)):
    """
    Upsert heritage context text for the SHREE chatbot.
    Omit node_id for a site-level prompt (used as fallback for all nodes).
    Include node_id for a node-specific prompt (overrides site-level when at that node).
    """
    existing = db.query(Prompt).filter(
        Prompt.site_id == payload.site_id,
        Prompt.node_id == payload.node_id,
    ).first()
    if existing:
        existing.context_prompt_text = payload.prompt_text
        db.commit()
        return {"success": True, "action": "updated", "site_id": payload.site_id, "node_id": payload.node_id}
    db.add(Prompt(site_id=payload.site_id, node_id=payload.node_id, context_prompt_text=payload.prompt_text))
    db.commit()
    return {"success": True, "action": "created", "site_id": payload.site_id, "node_id": payload.node_id}


@router.get("/prompts/{site_id}")
def list_prompts(site_id: int, db: Session = Depends(get_db)):
    """Debug: list all seeded prompts for a site."""
    prompts = db.query(Prompt).filter(Prompt.site_id == site_id).all()
    return [{"id": p.id, "node_id": p.node_id, "preview": p.context_prompt_text[:120] + "..."} for p in prompts]    