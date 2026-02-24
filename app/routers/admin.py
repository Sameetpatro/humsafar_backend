import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import HeritageSite, SiteImage, Node, NodeImage, Recommendation

logger = logging.getLogger(__name__)

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "your_secret_here")

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Pydantic schemas for seed payload ────────────────────────────────────────

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


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/seed-bulk")
def seed_bulk(
    payload: SeedBulkRequest,
    db: Session = Depends(get_db),
    x_admin_secret: Optional[str] = Header(None),
):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized — invalid admin secret")

    # ── 1. Create HeritageSite ────────────────────────────────────────────
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
    db.flush()  # get site.id before committing

    # ── 2. Site images ────────────────────────────────────────────────────
    for order, url in enumerate(payload.site.images):
        if url:
            db.add(SiteImage(site_id=site.id, image_url=url, display_order=order))

    # ── 3. Nodes ──────────────────────────────────────────────────────────
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
        db.flush()  # get node.id

        for order, url in enumerate(node_data.images):
            if url:
                db.add(NodeImage(node_id=node.id, image_url=url, display_order=order))

    # ── 4. Landmarks / Recommendations ───────────────────────────────────
    if payload.landmarks:
        type_map = {
            "monument": payload.landmarks.monuments,
            "restaurant": payload.landmarks.restaurants,
            "hotel": payload.landmarks.hotels,
        }
        for ltype, items in type_map.items():
            for item in items:
                if item.name:
                    db.add(Recommendation(
                        site_id=site.id,
                        type=ltype,
                        name=item.name,
                        latitude=item.latitude,
                        longitude=item.longitude,
                    ))

    db.commit()
    logger.info(f"[seed-bulk] Created site '{site.name}' id={site.id}")

    return {
        "success": True,
        "site_id": site.id,
        "site_name": site.name,
        "nodes_created": len(payload.nodes),
    }