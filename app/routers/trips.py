# app/routers/trips.py
# UPGRADED:
#   - start_trip now accepts firebase_uid and resolves to users.id (UUID)
#   - end_trip uses UUID in user_visit_history insert
#   - entry_lat/entry_lng stored on Trip row at start

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone

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
    Start a trip by scanning any valid node QR code.
    Requires the user to be registered (POST /users/register) first.

    A trip can be started from any node — the king node is a hint for the
    "main entrance" but not a hard requirement, since heritage sites often
    have multiple entry points.
    """
    user_uuid = get_user_uuid(firebase_uid, db)

    node = db.query(Node).filter(Node.qr_code_value == qr_value).first()
    if not node:
        raise HTTPException(status_code=400, detail="Invalid QR Code")

    trip = Trip(
        user_id    = user_uuid,
        site_id    = node.site_id,
        started_at = datetime.now(timezone.utc),  # tz-aware to match TIMESTAMPTZ
        is_active  = True,
        entry_lat  = entry_lat,
        entry_lng  = entry_lng,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)

    return {
        "message":     "Trip Started",
        "trip_id":     trip.id,
        "site_id":     node.site_id,
        "started_from_king": bool(node.is_king),
    }


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
    # Use a tz-aware UTC timestamp; the column is TIMESTAMPTZ so a naive
    # datetime here would crash on `ended_at - started_at` below with
    # "can't subtract offset-naive and offset-aware datetimes".
    trip.ended_at  = datetime.now(timezone.utc)

    site      = db.query(HeritageSite).filter(HeritageSite.id == trip.site_id).first()
    site_name = site.name if site else "Unknown"

    node_ids = []
    if visited_nodes:
        node_ids = [int(x.strip()) for x in visited_nodes.split(",") if x.strip().isdigit()]

    total_nodes    = db.query(Node).filter(Node.site_id == trip.site_id).count()
    nodes_completed = len(node_ids)

    duration_mins = None
    if trip.started_at and trip.ended_at:
        # Defensive: align tz-awareness on both sides before subtracting.
        # Postgres TIMESTAMPTZ comes back tz-aware, but if any historical
        # row was inserted with a naive value (older deploys did
        # datetime.utcnow()), the subtraction would TypeError.
        started = trip.started_at
        ended   = trip.ended_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if ended.tzinfo is None:
            ended   = ended.replace(tzinfo=timezone.utc)
        delta = ended - started
        duration_mins = max(0, int(delta.total_seconds() / 60))

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