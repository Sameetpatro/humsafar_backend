# app/routers/gems.py
# Wallet endpoints: read balance + recent ledger, and a manual testing grant.

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, GemTransaction
from app.routers.users import get_user_uuid
from app.schemas import GemBalanceResponse, GemTransactionItem
from app.services import gems as gems_service

router = APIRouter(prefix="/gems", tags=["Gems"])


def _balance_response(db: Session, user_uuid, limit: int = 20) -> GemBalanceResponse:
    user = db.query(User).filter(User.id == user_uuid).first()
    rows = (
        db.query(GemTransaction)
        .filter(GemTransaction.user_id == user_uuid)
        .order_by(GemTransaction.created_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return GemBalanceResponse(
        gems=int(user.gems or 0) if user else 0,
        history=[GemTransactionItem.model_validate(r) for r in rows],
    )


@router.get("/{firebase_uid}", response_model=GemBalanceResponse)
def get_gems(firebase_uid: str, limit: int = 20, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)
    return _balance_response(db, user_uuid, limit)


@router.post("/{firebase_uid}/grant", response_model=GemBalanceResponse)
def grant_gems(
    firebase_uid: str,
    amount: int = 0,
    set_to: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    TESTING helper — manually adjust a user's gem balance.
      • ?amount=N      → add N gems (use a negative N to remove).
      • ?set_to=N      → set the wallet to exactly N (overrides amount).
    The change is written through the normal ledger (reason="adjust").
    """
    user_uuid = get_user_uuid(firebase_uid, db)

    if set_to is not None:
        if set_to < 0:
            raise HTTPException(status_code=400, detail="set_to cannot be negative")
        current = gems_service.get_balance(db, user_uuid)
        delta = set_to - current
    else:
        delta = amount

    if delta != 0:
        try:
            gems_service.credit(db, user_uuid, delta, reason="adjust", ref_id="manual")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return _balance_response(db, user_uuid)
