# app/routers/instants.py
# Instagram-style user moments per heritage node.
# Client uploads media to Firebase Storage, then POSTs the public URL here.
#
# Retention: 34 h TTL per instant; max 50 per node (by likes, then recency).

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from app.database import get_db
from app.models import NodeInstant, NodeInstantLike, Node, HeritageSite, User
from app.routers.users import get_user_uuid
from app.schemas import NodeInstantCreate, NodeInstantResponse, NodeInstantLikeResponse
from app.services.instants_cleanup import (
    cleanup_node_instants,
    instant_expiry_cutoff,
    MAX_INSTANTS_PER_NODE,
)

router = APIRouter(prefix="/instants", tags=["Instants"])

MAX_CAPTION_LENGTH = 500
MAX_FEED_LIMIT = MAX_INSTANTS_PER_NODE


def _photographer_label(user: User) -> str:
    """Best-effort display name for whoever captured/posted the instant."""
    if user.display_name and user.display_name.strip():
        return user.display_name.strip()
    if user.email and "@" in user.email:
        return user.email.split("@")[0].replace(".", " ").title()
    if user.phone and user.phone.strip():
        return user.phone.strip()
    if user.is_anonymous:
        return "Guest Traveller"
    return "Traveller"


def _hydrate_instant(row, liked: bool = False) -> NodeInstantResponse:
    name = (
        getattr(row, "photographer_name", None)
        or getattr(row, "display_name", None)
        or "Traveller"
    )
    return NodeInstantResponse(
        id           = row.id,
        user_id      = row.user_id,
        site_id      = row.site_id,
        node_id      = row.node_id,
        media_url    = row.media_url,
        media_type   = row.media_type,
        caption      = row.caption,
        like_count   = int(row.like_count or 0),
        created_at   = row.created_at,
        display_name = name,
        avatar_url   = row.avatar_url,
        liked_by_me  = liked,
    )


@router.get("/node/{node_id}", response_model=List[NodeInstantResponse])
def get_node_instants(
    node_id:      int,
    limit:        int = Query(default=MAX_FEED_LIMIT, le=MAX_FEED_LIMIT, ge=1),
    firebase_uid: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Top instants for a node, ranked by likes then recency. Max 50.
    Pass firebase_uid to populate liked_by_me.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    cleanup_node_instants(db, node_id)
    cutoff = instant_expiry_cutoff()

    current_uuid: Optional[str] = None
    if firebase_uid:
        try:
            current_uuid = str(get_user_uuid(firebase_uid, db))
        except HTTPException:
            current_uuid = None

    rows = db.execute(
        text("""
            SELECT
                i.id, i.user_id, i.site_id, i.node_id,
                i.media_url, i.media_type, i.caption, i.like_count, i.created_at,
                i.photographer_name,
                u.display_name AS display_name,
                u.avatar_url   AS avatar_url
            FROM node_instants i
            LEFT JOIN users u ON u.id = i.user_id
            WHERE i.node_id = :nid AND i.is_flagged = FALSE
              AND i.created_at >= :cutoff
            ORDER BY i.like_count DESC, i.created_at DESC
            LIMIT :lim
        """),
        {"nid": node_id, "cutoff": cutoff, "lim": limit},
    ).fetchall()

    liked_ids: set[int] = set()
    if current_uuid and rows:
        ids = [r.id for r in rows]
        liked_rows = (
            db.query(NodeInstantLike.instant_id)
            .filter(
                NodeInstantLike.user_id == current_uuid,
                NodeInstantLike.instant_id.in_(ids),
            )
            .all()
        )
        liked_ids = {r.instant_id for r in liked_rows}

    return [_hydrate_instant(r, r.id in liked_ids) for r in rows]


@router.post("", response_model=NodeInstantResponse, status_code=201)
def create_instant(payload: NodeInstantCreate, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(payload.firebase_uid, db)

    node = db.query(Node).filter(Node.id == payload.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.site_id != payload.site_id:
        raise HTTPException(status_code=400, detail="site_id does not match node")

    site = db.query(HeritageSite).filter(HeritageSite.id == payload.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    media_url = (payload.media_url or "").strip()
    if not media_url:
        raise HTTPException(status_code=400, detail="media_url is required")

    media_type = (payload.media_type or "image").lower()
    if media_type not in ("image", "video"):
        raise HTTPException(status_code=400, detail="media_type must be image or video")

    caption = (payload.caption or "").strip() or None
    if caption and len(caption) > MAX_CAPTION_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Caption too long (max {MAX_CAPTION_LENGTH} chars)",
        )

    user = db.query(User).filter(User.id == user_uuid).first()
    photographer = _photographer_label(user) if user else "Traveller"

    instant = NodeInstant(
        user_id    = user_uuid,
        site_id    = payload.site_id,
        node_id    = payload.node_id,
        media_url  = media_url,
        media_type = media_type,
        caption    = caption,
        photographer_name = photographer,
    )
    db.add(instant)
    db.commit()
    db.refresh(instant)

    cleanup_node_instants(db, payload.node_id)

    user = db.query(User).filter(User.id == user_uuid).first()
    return NodeInstantResponse(
        id           = instant.id,
        user_id      = instant.user_id,
        site_id      = instant.site_id,
        node_id      = instant.node_id,
        media_url    = instant.media_url,
        media_type   = instant.media_type,
        caption      = instant.caption,
        like_count   = 0,
        created_at   = instant.created_at,
        display_name = photographer,
        avatar_url   = user.avatar_url if user else None,
        liked_by_me  = False,
    )


@router.post("/{instant_id}/like", response_model=NodeInstantLikeResponse)
def toggle_like(instant_id: int, firebase_uid: str, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)
    instant = db.query(NodeInstant).filter(NodeInstant.id == instant_id).first()
    if not instant or instant.is_flagged:
        raise HTTPException(status_code=404, detail="Instant not found")

    existing = (
        db.query(NodeInstantLike)
        .filter(
            NodeInstantLike.instant_id == instant_id,
            NodeInstantLike.user_id == user_uuid,
        )
        .first()
    )

    if existing:
        db.delete(existing)
        instant.like_count = max(0, (instant.like_count or 0) - 1)
        liked = False
    else:
        db.add(NodeInstantLike(instant_id=instant_id, user_id=user_uuid))
        instant.like_count = (instant.like_count or 0) + 1
        liked = True

    db.commit()
    db.refresh(instant)
    return NodeInstantLikeResponse(
        instant_id = instant_id,
        liked      = liked,
        like_count = instant.like_count,
    )


@router.delete("/{instant_id}", status_code=204)
def delete_instant(instant_id: int, firebase_uid: str, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)
    instant = db.query(NodeInstant).filter(NodeInstant.id == instant_id).first()
    if not instant:
        raise HTTPException(status_code=404, detail="Instant not found")
    if instant.user_id != user_uuid:
        raise HTTPException(status_code=403, detail="Cannot delete another user's instant")
    db.delete(instant)
    db.commit()
