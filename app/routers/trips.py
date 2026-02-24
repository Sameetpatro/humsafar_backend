from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import Trip, Node

router = APIRouter(prefix="/trips", tags=["Trips"])


@router.post("/start")
def start_trip(user_id: int, qr_value: str, db: Session = Depends(get_db)):

    node = db.query(Node).filter(Node.qr_code_value == qr_value).first()

    if not node:
        raise HTTPException(status_code=400, detail="Invalid QR Code")

    # must be king node (sequence_order = 0)
    if node.sequence_order != 0:
        raise HTTPException(status_code=400, detail="This is not a King Node")

    trip = Trip(
        user_id=user_id,
        site_id=node.site_id,
        started_at=datetime.utcnow(),
        is_active=True
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
    trip.ended_at = datetime.utcnow()

    db.commit()

    return {"message": "Trip Ended"}