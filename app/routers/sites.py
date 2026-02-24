from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import HeritageSite
from app.utils import haversine
from app.models import Node

router = APIRouter(prefix="/sites", tags=["Sites"])

@router.get("/scan/{qr_value}")
def scan_qr(qr_value: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.qr_code_value == qr_value).first()

    if not node:
        return {"status": "invalid"}

    return {
        "status": "valid",
        "site_id": node.site_id,
        "node_id": node.id,
        "sequence_order": node.sequence_order,
        "node_name": node.name
    }

@router.get("/nearby")
def get_nearby_sites(lat: float, lng: float, max_range_km: float = 100, db: Session = Depends(get_db)):

    sites = db.query(HeritageSite).all()
    result = []

    for site in sites:
        distance = haversine(lat, lng, site.latitude, site.longitude)

        if distance <= max_range_km * 1000:
            result.append({
                "id": site.id,
                "name": site.name,
                "distance_meters": round(distance),
                "inside_geofence": distance <= site.geofence_radius_meters
            })

    return result


@router.get("/{site_id}")
def get_site_details(site_id: int, db: Session = Depends(get_db)):
    site = db.query(HeritageSite).filter(HeritageSite.id == site_id).first()

    return site

