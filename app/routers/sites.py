# app/routers/sites.py
# FIXED:
#   1. get_site_details now uses response_model=SiteDetailResponse and explicitly
#      loads images + nodes relationships before the DB session closes.
#      Previously returning raw `site` ORM object caused lazy-load to fail → nodes=[]
#      which made NodeDetailViewModel always hit "Node not found in site".
#   2. get_nearby_sites response typed properly.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import HeritageSite, Node
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
                "distance_meters": round(distance),
                "inside_geofence": distance <= site.geofence_radius_meters,
            })

    return result


@router.get("/{site_id}", response_model=SiteDetailResponse)
def get_site_details(site_id: int, db: Session = Depends(get_db)):
    # Use joinedload so SQLAlchemy fetches images + nodes in the SAME query.
    # Without this, the ORM lazy-loads them AFTER the session would close,
    # returning empty lists and breaking NodeDetailViewModel.
    site = (
        db.query(HeritageSite)
        .options(
            joinedload(HeritageSite.images),
            joinedload(HeritageSite.nodes),
        )
        .filter(HeritageSite.id == site_id)
        .first()
    )

    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")

    return site