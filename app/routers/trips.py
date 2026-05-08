# app/routers/trips.py
# UPGRADED:
#   - start_trip now accepts firebase_uid and resolves to users.id (UUID)
#   - end_trip uses UUID in user_visit_history insert
#   - entry_lat/entry_lng stored on Trip row at start

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

from app.database import get_db
from app.models import Trip, Node, HeritageSite
from app.routers.users import get_user_uuid

router = APIRouter(prefix="/trips", tags=["Trips"])


@router.post("/start")
def start_trip(
    firebase_uid: str,
    qr_value: str,
    entry_lat: float | None = None,
    entry_lng: float | None = None,
    db: Session = Depends(get_db),
):
    """
    Start a trip by scanning the King QR code.
    Requires the user to be registered (POST /users/register) first.
    """
    user_uuid = get_user_uuid(firebase_uid, db)

    node = db.query(Node).filter(Node.qr_code_value == qr_value).first()
    if not node:
        raise HTTPException(status_code=400, detail="Invalid QR Code")

    if not node.is_king:
        raise HTTPException(
            status_code=400,
            detail=f"Node '{node.name}' is not a King Node. Scan the main entrance QR to start a trip.",
        )

    trip = Trip(
        user_id    = user_uuid,
        site_id    = node.site_id,
        started_at = datetime.utcnow(),
        is_active  = True,
        entry_lat  = entry_lat,
        entry_lng  = entry_lng,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)

    return {"message": "Trip Started", "trip_id": trip.id, "site_id": node.site_id}


@router.post("/end")
def end_trip(
    trip_id: int,
    visited_nodes: str | None = None,   # comma-separated node IDs e.g. "1,2,5"
    db: Session = Depends(get_db),
):
    """
    End an active trip. Records visit history with nodes visited.
    """
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    trip.is_active = False
    trip.ended_at  = datetime.utcnow()

    site      = db.query(HeritageSite).filter(HeritageSite.id == trip.site_id).first()
    site_name = site.name if site else "Unknown"

    node_ids = []
    if visited_nodes:
        node_ids = [int(x.strip()) for x in visited_nodes.split(",") if x.strip().isdigit()]

    total_nodes    = db.query(Node).filter(Node.site_id == trip.site_id).count()
    nodes_completed = len(node_ids)

    duration_mins = None
    if trip.started_at and trip.ended_at:
        delta = trip.ended_at - trip.started_at
        duration_mins = int(delta.total_seconds() / 60)

    try:
        db.execute(
            text("""
                INSERT INTO user_visit_history
                    (user_id, site_id, trip_id, site_name, nodes_visited, total_nodes,
                     nodes_completed, completed, visited_at, ended_at, duration_mins,
                     entry_lat, entry_lng)
                VALUES
                    (:user_id, :site_id, :trip_id, :site_name, :nodes_visited, :total_nodes,
                     :nodes_completed, true, :visited_at, :ended_at, :duration_mins,
                     :entry_lat, :entry_lng)
                ON CONFLICT (user_id, trip_id) DO UPDATE SET
                    ended_at        = EXCLUDED.ended_at,
                    duration_mins   = EXCLUDED.duration_mins,
                    nodes_visited   = EXCLUDED.nodes_visited,
                    nodes_completed = EXCLUDED.nodes_completed
            """),
            {
                "user_id":        str(trip.user_id),
                "site_id":        trip.site_id,
                "trip_id":        trip.id,
                "site_name":      site_name,
                "nodes_visited":  node_ids,
                "total_nodes":    total_nodes,
                "nodes_completed": nodes_completed,
                "visited_at":     trip.started_at,
                "ended_at":       trip.ended_at,
                "duration_mins":  duration_mins,
                "entry_lat":      trip.entry_lat,
                "entry_lng":      trip.entry_lng,
            }
        )
    except Exception as e:
        # Log but don't fail — trip end is more important than history write
        import logging
        logging.getLogger(__name__).warning(f"[end_trip] visit history insert failed: {e}")

    db.commit()
    return {"message": "Trip Ended", "duration_mins": duration_mins}


@router.get("/active/{firebase_uid}")
def get_active_trip(firebase_uid: str, db: Session = Depends(get_db)):
    """Return the current active trip for a user, if any."""
    user_uuid = get_user_uuid(firebase_uid, db)
    trip = (
        db.query(Trip)
        .filter(Trip.user_id == user_uuid, Trip.is_active == True)
        .order_by(Trip.started_at.desc())
        .first()
    )
    if not trip:
        return {"active": False}
    return {
        "active":      True,
        "trip_id":     trip.id,
        "site_id":     trip.site_id,
        "started_at":  trip.started_at.isoformat(),
    }