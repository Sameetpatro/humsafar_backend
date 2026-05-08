# app/routers/users.py
# Firebase-aware user registration and profile management.
# Pattern: Android calls POST /users/register on every app open.
#   - If firebase_uid exists: update last_active_at, return user.
#   - If new: create user row, return user.
# All other tables reference users.id (UUID) — never the raw firebase_uid.

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.models import User
from app.schemas import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


def get_user_uuid(firebase_uid: str, db: Session) -> uuid.UUID:
    """
    Utility used by other routers to resolve firebase_uid → users.id (UUID).
    Raises 404 if the user has not registered yet.
    """
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"User with firebase_uid '{firebase_uid}' not found. Call POST /users/register first."
        )
    return user.id


@router.post("/register", response_model=UserResponse)
def register_or_update(payload: UserCreate, db: Session = Depends(get_db)):
    """
    Upsert user by firebase_uid.
    Safe to call on every app launch — idempotent.
    """
    user = db.query(User).filter(User.firebase_uid == payload.firebase_uid).first()

    if user:
        # Update mutable fields and last_active_at
        if payload.display_name is not None:
            user.display_name = payload.display_name
        if payload.email is not None:
            user.email = payload.email
        if payload.avatar_url is not None:
            user.avatar_url = payload.avatar_url
        if payload.preferred_lang:
            user.preferred_lang = payload.preferred_lang
        db.execute(
            text("UPDATE users SET last_active_at = now() WHERE firebase_uid = :uid"),
            {"uid": payload.firebase_uid}
        )
        db.commit()
        db.refresh(user)
        return user

    # New user
    user = User(
        firebase_uid   = payload.firebase_uid,
        display_name   = payload.display_name,
        email          = payload.email,
        phone          = payload.phone,
        avatar_url     = payload.avatar_url,
        preferred_lang = payload.preferred_lang,
        is_anonymous   = payload.is_anonymous,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{firebase_uid}", response_model=UserResponse)
def get_user(firebase_uid: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/{firebase_uid}", status_code=204)
def delete_user(firebase_uid: str, db: Session = Depends(get_db)):
    """Hard delete. Cascades to all child rows per FK rules."""
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()