# app/routers/trips.py
# FIXED:
#   user_id changed from int → str so that the Android client can pass
#   TripManager.USER_ID = "guest_user_001" without getting a 422 Unprocessable Entity.
#   Previously `user_id: int` caused FastAPI to reject the string value immediately.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import Trip, Node

router = APIRouter(prefix="/trips", tags=["Trips"])


@router.post("/start")
def start_trip(user_id: str, qr_value: str, db: Session = Depends(get_db)):

    node = db.query(Node).filter(Node.qr_code_value == qr_value).first()

    if not node:
        raise HTTPException(status_code=400, detail="Invalid QR Code")

    if not node.is_king:
        raise HTTPException(
            status_code=400,
            detail=f"Node '{node.name}' is not a King Node. "
                   f"Scan the main entrance QR to start a trip."
        )

    try:
        uid_int = int(user_id)
    except (ValueError, TypeError):
        uid_int = 0

    trip = Trip(
        user_id=uid_int,
        site_id=node.site_id,
        started_at=datetime.utcnow(),
        is_active=True,
    )

    db.add(trip)
    db.commit()
    db.refresh(trip)

    return {"message": "Trip Started", "trip_id": trip.id}

@router.post("/end")
def end_trip(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    trip.is_active = False
    trip.ended_at  = datetime.utcnow()

    db.commit()

    return {"message": "Trip Ended"}