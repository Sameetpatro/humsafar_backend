# app/routers/amenities.py

import math
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import Amenity, HeritageSite, Node
from app.schemas import AmenityResponse
from app.utils import haversine

router = APIRouter(prefix="/amenities", tags=["Amenities"])


class AmenityPayload(BaseModel):
    type:        str
    name:        str
    description: Optional[str] = None
    latitude:    float
    longitude:   float
    price_info:  Optional[str] = None
    timing:      Optional[str] = None
    is_paid:     bool = False
    node_id:     Optional[int] = None


class SeedAmenitiesRequest(BaseModel):
    site_id:   int
    amenities: List[AmenityPayload]


@router.post("/seed")
def seed_amenities(payload: SeedAmenitiesRequest, db: Session = Depends(get_db)):
    site = db.query(HeritageSite).filter(HeritageSite.id == payload.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {payload.site_id} not found")

    created = []
    for item in payload.amenities:
        amenity = Amenity(
            site_id     = payload.site_id,
            node_id     = item.node_id,
            type        = item.type.lower(),
            name        = item.name,
            description = item.description,
            latitude    = item.latitude,
            longitude   = item.longitude,
            price_info  = item.price_info,
            timing      = item.timing,
            is_paid     = item.is_paid,
        )
        db.add(amenity)
        db.flush()
        created.append(amenity.id)

    db.commit()
    return {"success": True, "created_ids": created, "count": len(created)}


@router.get("/near-node", response_model=List[AmenityResponse])
def get_amenities_near_node(
    node_id: int,
    top_n:   int = 2,
    db: Session = Depends(get_db),
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    all_amenities = (
        db.query(Amenity)
        .filter(Amenity.site_id == node.site_id)
        .all()
    )

    def with_distance(a: Amenity) -> dict:
        dist = haversine(node.latitude, node.longitude, a.latitude, a.longitude)
        return {
            "id":              a.id,
            "site_id":         a.site_id,
            "node_id":         a.node_id,
            "type":            a.type,
            "name":            a.name,
            "description":     a.description,
            "latitude":        a.latitude,
            "longitude":       a.longitude,
            "price_info":      a.price_info,
            "timing":          a.timing,
            "is_paid":         a.is_paid,
            "distance_meters": round(dist),
        }

    enriched  = [with_distance(a) for a in all_amenities]
    washrooms = sorted([e for e in enriched if e["type"] == "washroom"], key=lambda x: x["distance_meters"])[:top_n]
    shops     = sorted([e for e in enriched if e["type"] == "shop"],     key=lambda x: x["distance_meters"])[:top_n]

    return washrooms + shops


@router.get("/site/{site_id}", response_model=List[AmenityResponse])
def get_site_amenities(
    site_id: int,
    type:    Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Amenity).filter(Amenity.site_id == site_id)
    if type:
        query = query.filter(Amenity.type == type.lower())
    return query.all()


@router.get("/{amenity_id}", response_model=AmenityResponse)
def get_amenity_detail(amenity_id: int, db: Session = Depends(get_db)):
    amenity = db.query(Amenity).filter(Amenity.id == amenity_id).first()
    if not amenity:
        raise HTTPException(status_code=404, detail=f"Amenity {amenity_id} not found")
    return amenity