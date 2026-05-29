# app/routers/stats.py
#
# App-wide live stats:
#   - active_users   : distinct users seen in the last ACTIVE_WINDOW_MIN minutes
#                      (derived live from users.last_active_at)
#   - lifetime_visits: cumulative app opens, persisted in global_stats (id=1)
#   - total_users    : distinct registered users
#
# The Android app calls POST /stats/visit once per cold start and POST
# /stats/heartbeat periodically while open so "active now" stays fresh.

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, GlobalStats
from app.schemas import LiveStatsResponse

router = APIRouter(prefix="/stats", tags=["Stats"])

ACTIVE_WINDOW_MIN = 5


def _get_or_create_stats(db: Session) -> GlobalStats:
    row = db.query(GlobalStats).filter(GlobalStats.id == 1).first()
    if not row:
        row = GlobalStats(id=1, lifetime_visits=0)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _live(db: Session) -> LiveStatsResponse:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ACTIVE_WINDOW_MIN)
    active = db.query(func.count(User.id)).filter(User.last_active_at >= cutoff).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0
    stats = _get_or_create_stats(db)
    return LiveStatsResponse(
        active_users=int(active),
        lifetime_visits=int(stats.lifetime_visits or 0),
        total_users=int(total_users),
    )


@router.get("/live", response_model=LiveStatsResponse)
def get_live_stats(db: Session = Depends(get_db)):
    return _live(db)


@router.post("/heartbeat", response_model=LiveStatsResponse)
def heartbeat(firebase_uid: Optional[str] = None, db: Session = Depends(get_db)):
    """Keep a signed-in user counted as 'active now'. Safe to call anonymously."""
    if firebase_uid:
        db.execute(
            text("UPDATE users SET last_active_at = now() WHERE firebase_uid = :uid"),
            {"uid": firebase_uid},
        )
        db.commit()
    return _live(db)


@router.post("/visit", response_model=LiveStatsResponse)
def record_visit(firebase_uid: Optional[str] = None, db: Session = Depends(get_db)):
    """Increment the lifetime visit counter (called once per app cold start)."""
    stats = _get_or_create_stats(db)
    stats.lifetime_visits = int(stats.lifetime_visits or 0) + 1
    if firebase_uid:
        db.execute(
            text("UPDATE users SET last_active_at = now() WHERE firebase_uid = :uid"),
            {"uid": firebase_uid},
        )
    db.commit()
    return _live(db)
