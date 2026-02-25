# app/routers/admin.py
import logging
from fastapi import APIRouter, Depends, HTTPException
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

    # 🔥 Enforce exactly ONE king node
    king_count = sum(1 for n in payload.nodes if getattr(n, "is_king", False))
    if king_count != 1:
        raise HTTPException(
            status_code=400,
            detail="Exactly ONE king node must be defined per site."
        )

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
            is_king=getattr(node_data, "is_king", False),
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
        for ltype, items in {
            "monument": payload.landmarks.monuments,
            "restaurant": payload.landmarks.restaurants,
            "hotel": payload.landmarks.hotels
        }.items():
            for item in items:
                if item.name:
                    db.add(Recommendation(
                        site_id=site.id,
                        type=ltype,
                        name=item.name,
                        latitude=item.latitude,
                        longitude=item.longitude
                    ))

    db.commit()

    return {
        "success": True,
        "site_id": site.id,
        "site_name": site.name,
        "nodes_created": len(payload.nodes)
    }