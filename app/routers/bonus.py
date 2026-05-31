# app/routers/bonus.py
# Surprise location challenge ("Bingo bonus"). The app offers a target node to
# reach + scan within a deadline; doing so unlocks a single random minigame.
# Solving it awards a pre-rolled 100-200 gems. The reward is decided server-side
# at offer time and only paid out once the scan + solve are confirmed.

import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Node, HeritageSite, BonusChallenge
from app.routers.users import get_user_uuid
from app.schemas import (
    BonusOfferRequest,
    BonusOfferResponse,
    BonusCompleteRequest,
    BonusCompleteResponse,
)
from app.services import gems

router = APIRouter(prefix="/bonus", tags=["Bonus"])

MINIGAMES = ["zip", "sudoku"]
DEADLINE_CHOICES = [20, 30, 35]   # minutes
REWARD_MIN, REWARD_MAX = 100, 200


@router.post("/offer", response_model=BonusOfferResponse)
def offer_bonus(req: BonusOfferRequest, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(req.firebase_uid, db)

    site = db.query(HeritageSite).filter(HeritageSite.id == req.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {req.site_id} not found")

    nodes = db.query(Node).filter(Node.site_id == req.site_id).all()
    if not nodes:
        raise HTTPException(status_code=400, detail="Site has no nodes")

    # Prefer a node other than the one the user is standing at, for variety.
    pool = [n for n in nodes if n.id != req.exclude_node_id] or nodes
    target = random.choice(pool)

    minutes = random.choice(DEADLINE_CHOICES)
    reward = random.randint(REWARD_MIN, REWARD_MAX)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=minutes)

    # Expire any still-open offers so only one is active at a time.
    db.query(BonusChallenge).filter(
        BonusChallenge.user_id == user_uuid,
        BonusChallenge.status.in_(["offered", "reached"]),
    ).update({BonusChallenge.status: "expired"}, synchronize_session=False)

    challenge = BonusChallenge(
        user_id=user_uuid,
        site_id=req.site_id,
        target_node_id=target.id,
        minigame=random.choice(MINIGAMES),
        reward_gems=reward,
        status="offered",
        expires_at=expires_at,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    return BonusOfferResponse(
        challenge_id=challenge.id,
        target_node_id=target.id,
        target_node_name=target.name,
        minigame=challenge.minigame,
        deadline_minutes=minutes,
        expires_at=challenge.expires_at,
    )


@router.post("/complete", response_model=BonusCompleteResponse)
def complete_bonus(req: BonusCompleteRequest, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(req.firebase_uid, db)

    challenge = db.query(BonusChallenge).filter(
        BonusChallenge.id == req.challenge_id,
        BonusChallenge.user_id == user_uuid,
    ).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Bonus challenge not found")

    # Idempotent success.
    if challenge.status == "completed":
        return BonusCompleteResponse(
            status="completed",
            reward_gems=challenge.reward_gems,
            new_balance=gems.get_balance(db, user_uuid),
        )

    now = datetime.now(timezone.utc)
    expires_at = challenge.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and now > expires_at:
        challenge.status = "expired"
        db.commit()
        return BonusCompleteResponse(status="expired", reward_gems=0,
                                     new_balance=gems.get_balance(db, user_uuid))

    if req.scanned_node_id != challenge.target_node_id:
        return BonusCompleteResponse(status="wrong_node", reward_gems=0,
                                     new_balance=gems.get_balance(db, user_uuid))

    if not req.solved:
        # Reached the node but minigame not solved yet — keep it open.
        challenge.status = "reached"
        db.commit()
        return BonusCompleteResponse(status="not_solved", reward_gems=0,
                                     new_balance=gems.get_balance(db, user_uuid))

    challenge.status = "completed"
    challenge.completed_at = now
    new_balance = gems.credit(db, user_uuid, challenge.reward_gems, reason="bonus_game",
                              ref_id=str(challenge.id), commit=False)
    db.commit()
    return BonusCompleteResponse(status="completed", reward_gems=challenge.reward_gems,
                                 new_balance=new_balance)
