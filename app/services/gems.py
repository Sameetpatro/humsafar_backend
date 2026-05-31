# app/services/gems.py
# Single source of truth for moving gems in/out of a user's wallet.
# Every change updates users.gems AND writes a GemTransaction ledger row in the
# same transaction so the balance and the audit trail can never drift.

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models import User, GemTransaction


def get_balance(db: Session, user_id: uuid.UUID) -> int:
    user = db.query(User).filter(User.id == user_id).first()
    return int(user.gems or 0) if user else 0


def credit(
    db: Session,
    user_id: uuid.UUID,
    delta: int,
    reason: str,
    ref_id: Optional[str] = None,
    commit: bool = True,
) -> int:
    """
    Add (delta > 0) or remove (delta < 0) gems and append a ledger row.
    Returns the new balance. Caller is responsible for catching exceptions;
    on commit=False the caller controls the transaction boundary.
    """
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if user is None:
        raise ValueError("user not found")

    new_balance = int(user.gems or 0) + int(delta)
    if new_balance < 0:
        raise ValueError("insufficient gems")

    user.gems = new_balance
    db.add(GemTransaction(
        user_id=user_id,
        delta=int(delta),
        reason=reason,
        ref_id=str(ref_id) if ref_id is not None else None,
        balance_after=new_balance,
    ))
    if commit:
        db.commit()
    return new_balance


def debit(db: Session, user_id: uuid.UUID, amount: int, reason: str,
          ref_id: Optional[str] = None, commit: bool = True) -> int:
    """Convenience wrapper for spending gems. Raises ValueError if too few."""
    if amount < 0:
        raise ValueError("amount must be positive")
    return credit(db, user_id, -amount, reason, ref_id, commit)
