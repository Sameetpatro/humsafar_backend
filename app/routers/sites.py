# app/routers/sites.py
# UPDATED: joinedload(Node.images) so NodeDetailScreen gets node_images

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import HeritageSite, Node, NodeImage
from app.utils import haversine
from app.schemas import SiteDetailResponse, NearbySiteResponse

router = APIRouter(prefix="/sites", tags=["Sites"])


@router.get("/scan/{qr_value}")
def scan_qr(qr_value: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.qr_code_value == qr_value).first()
    if not node:
        return {"status": "invalid"}
    return {
        "status":         "valid",
        "site_id":        node.site_id,
        "node_id":        node.id,
        "sequence_order": node.sequence_order,
        "node_name":      node.name,
    }


@router.get("/nearby", response_model=list[NearbySiteResponse])
def get_nearby_sites(
    lat:          float,
    lng:          float,
    max_range_km: float = 100,
    db:           Session = Depends(get_db),
):
    sites  = db.query(HeritageSite).all()
    result = []
    for site in sites:
        distance = haversine(lat, lng, site.latitude, site.longitude)
        if distance <= max_range_km * 1000:
            result.append({
                "id":              site.id,
                "name":            site.name,
                "latitude":        site.latitude,
                "longitude":       site.longitude,
                "distance_meters": round(distance),
                "inside_geofence": distance <= site.geofence_radius_meters,
            })
    result.sort(key=lambda x: x["distance_meters"])
    return result


@router.get("/{site_id}", response_model=SiteDetailResponse)
def get_site_details(site_id: int, db: Session = Depends(get_db)):
    site = (
        db.query(HeritageSite)
        .options(
            joinedload(HeritageSite.images),
            # Load nodes AND each node's images in one query
            joinedload(HeritageSite.nodes).joinedload(Node.images),
        )
        .filter(HeritageSite.id == site_id)
        .first()
    )
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    return site