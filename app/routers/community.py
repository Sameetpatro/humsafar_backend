# app/routers/community.py
# Node comments and site feedback endpoints.
# Comments: flat 2-level threading (root post + replies). Replies-to-replies
#   are normalized server-side to the root parent so the UI can stay flat.
# Feedback: supports anonymous submissions (firebase_uid optional).

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from app.database import get_db
from app.models import NodeComment, SiteFeedback, Node, HeritageSite, User
from app.routers.users import get_user_uuid
from app.schemas import (
    NodeCommentCreate, NodeCommentResponse,
    SiteFeedbackCreate, SiteFeedbackResponse,
)

router = APIRouter(prefix="/community", tags=["Community"])

MAX_COMMENT_LENGTH = 2000


# ── Node Comments ─────────────────────────────────────────────────────────────

def _hydrate_comment_row(row, current_user_uuid: Optional[str] = None) -> NodeCommentResponse:
    """Convert a SQL row (joined comment + user) into a NodeCommentResponse."""
    return NodeCommentResponse(
        id                = row.id,
        user_id           = row.user_id,
        site_id           = row.site_id,
        node_id           = row.node_id,
        parent_comment_id = row.parent_comment_id,
        content           = row.content,
        is_flagged        = row.is_flagged,
        created_at        = row.created_at,
        display_name      = row.display_name,
        avatar_url        = row.avatar_url,
        reply_count       = int(row.reply_count or 0),
        is_own            = bool(current_user_uuid is not None
                                 and str(row.user_id) == str(current_user_uuid)),
    )


@router.post("/comments", response_model=NodeCommentResponse)
def add_comment(payload: NodeCommentCreate, db: Session = Depends(get_db)):
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Comment cannot be empty")
    if len(content) > MAX_COMMENT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Comment too long ({len(content)} chars, max {MAX_COMMENT_LENGTH})",
        )

    user_uuid = get_user_uuid(payload.firebase_uid, db)

    node = db.query(Node).filter(Node.id == payload.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Normalize replies to a single level: if the parent itself is a reply,
    # attach this new comment to the parent's parent so threads stay flat.
    parent_id: Optional[int] = None
    if payload.parent_comment_id is not None:
        parent = (
            db.query(NodeComment)
            .filter(NodeComment.id == payload.parent_comment_id)
            .first()
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent comment not found")
        if parent.node_id != payload.node_id:
            raise HTTPException(
                status_code=400,
                detail="Parent comment belongs to a different node",
            )
        if parent.is_flagged:
            raise HTTPException(status_code=400, detail="Cannot reply to a flagged comment")
        parent_id = parent.parent_comment_id or parent.id

    comment = NodeComment(
        user_id           = user_uuid,
        site_id           = payload.site_id,
        node_id           = payload.node_id,
        parent_comment_id = parent_id,
        content           = content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Build a hydrated response (single-row join with users + reply_count)
    user = db.query(User).filter(User.id == user_uuid).first()
    return NodeCommentResponse(
        id                = comment.id,
        user_id           = comment.user_id,
        site_id           = comment.site_id,
        node_id           = comment.node_id,
        parent_comment_id = comment.parent_comment_id,
        content           = comment.content,
        is_flagged        = comment.is_flagged,
        created_at        = comment.created_at,
        display_name      = user.display_name if user else None,
        avatar_url        = user.avatar_url if user else None,
        reply_count       = 0,
        is_own            = True,
    )


@router.get("/comments/node/{node_id}", response_model=List[NodeCommentResponse])
def get_node_comments(
    node_id:      int,
    page:         int = 1,
    page_size:    int = 20,
    firebase_uid: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Returns ROOT comments for a node (parent_comment_id IS NULL),
    most recent first. Each row carries a `reply_count` so the client
    knows whether to expose a "View replies" affordance.

    Pass `firebase_uid` to populate `is_own` on each row.
    """
    offset = max(0, (page - 1) * page_size)

    current_uuid: Optional[str] = None
    if firebase_uid:
        try:
            current_uuid = str(get_user_uuid(firebase_uid, db))
        except HTTPException:
            current_uuid = None

    rows = db.execute(
        text("""
            SELECT
                c.id, c.user_id, c.site_id, c.node_id, c.parent_comment_id,
                c.content, c.is_flagged, c.created_at,
                u.display_name AS display_name,
                u.avatar_url   AS avatar_url,
                (SELECT COUNT(*) FROM node_comments r
                  WHERE r.parent_comment_id = c.id AND r.is_flagged = FALSE
                ) AS reply_count
            FROM node_comments c
            LEFT JOIN users u ON u.id = c.user_id
            WHERE c.node_id = :nid
              AND c.is_flagged = FALSE
              AND c.parent_comment_id IS NULL
            ORDER BY c.created_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"nid": node_id, "lim": page_size, "off": offset},
    ).fetchall()

    return [_hydrate_comment_row(r, current_uuid) for r in rows]


@router.get("/comments/{comment_id}/replies", response_model=List[NodeCommentResponse])
def get_comment_replies(
    comment_id:   int,
    page:         int = 1,
    page_size:    int = 50,
    firebase_uid: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Replies of a root comment, oldest first (chronological reply order)."""
    offset = max(0, (page - 1) * page_size)

    current_uuid: Optional[str] = None
    if firebase_uid:
        try:
            current_uuid = str(get_user_uuid(firebase_uid, db))
        except HTTPException:
            current_uuid = None

    rows = db.execute(
        text("""
            SELECT
                c.id, c.user_id, c.site_id, c.node_id, c.parent_comment_id,
                c.content, c.is_flagged, c.created_at,
                u.display_name AS display_name,
                u.avatar_url   AS avatar_url,
                0              AS reply_count
            FROM node_comments c
            LEFT JOIN users u ON u.id = c.user_id
            WHERE c.parent_comment_id = :pid
              AND c.is_flagged = FALSE
            ORDER BY c.created_at ASC
            LIMIT :lim OFFSET :off
        """),
        {"pid": comment_id, "lim": page_size, "off": offset},
    ).fetchall()

    return [_hydrate_comment_row(r, current_uuid) for r in rows]


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, firebase_uid: str, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)
    comment = db.query(NodeComment).filter(NodeComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != user_uuid:
        raise HTTPException(status_code=403, detail="Cannot delete another user's comment")
    # Cascade in DB takes care of replies (parent_comment_id has ON DELETE CASCADE).
    db.delete(comment)
    db.commit()


@router.post("/comments/{comment_id}/flag", status_code=200)
def flag_comment(comment_id: int, db: Session = Depends(get_db)):
    comment = db.query(NodeComment).filter(NodeComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    comment.is_flagged = True
    db.commit()
    return {"flagged": True}


# ── Site Feedback ─────────────────────────────────────────────────────────────

@router.post("/feedback", response_model=SiteFeedbackResponse)
def submit_feedback(payload: SiteFeedbackCreate, db: Session = Depends(get_db)):
    site = db.query(HeritageSite).filter(HeritageSite.id == payload.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    user_uuid = None
    if payload.firebase_uid:
        try:
            user_uuid = get_user_uuid(payload.firebase_uid, db)
        except HTTPException:
            pass  # Anonymous fallback if user not found

    feedback = SiteFeedback(
        user_id  = user_uuid,
        site_id  = payload.site_id,
        category = payload.category,
        content  = payload.content,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


@router.get("/feedback/site/{site_id}", response_model=List[SiteFeedbackResponse])
def get_site_feedback(
    site_id:  int,
    status:   Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(SiteFeedback).filter(SiteFeedback.site_id == site_id)
    if status:
        query = query.filter(SiteFeedback.status == status)
    if category:
        query = query.filter(SiteFeedback.category == category)
    return query.order_by(SiteFeedback.created_at.desc()).all()


@router.patch("/feedback/{feedback_id}/status")
def update_feedback_status(
    feedback_id: int,
    status: str,
    db: Session = Depends(get_db),
):
    allowed = {"open", "reviewed", "resolved"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of: {allowed}")
    fb = db.query(SiteFeedback).filter(SiteFeedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    fb.status = status
    db.commit()
    return {"id": feedback_id, "status": status}