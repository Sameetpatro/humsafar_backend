# app/routers/community.py
# Node comments and site feedback endpoints.
# Comments: future release feature — schema is ready, endpoints wired.
# Feedback: supports anonymous submissions (firebase_uid optional).

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from app.database import get_db
from app.models import NodeComment, SiteFeedback, Node, HeritageSite
from app.routers.users import get_user_uuid
from app.schemas import (
    NodeCommentCreate, NodeCommentResponse,
    SiteFeedbackCreate, SiteFeedbackResponse,
)

router = APIRouter(prefix="/community", tags=["Community"])


# ── Node Comments ─────────────────────────────────────────────────────────────

@router.post("/comments", response_model=NodeCommentResponse)
def add_comment(payload: NodeCommentCreate, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(payload.firebase_uid, db)

    node = db.query(Node).filter(Node.id == payload.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    comment = NodeComment(
        user_id = user_uuid,
        site_id = payload.site_id,
        node_id = payload.node_id,
        content = payload.content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/comments/node/{node_id}", response_model=List[NodeCommentResponse])
def get_node_comments(
    node_id:   int,
    page:      int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    offset = (page - 1) * page_size
    return (
        db.query(NodeComment)
        .filter(NodeComment.node_id == node_id, NodeComment.is_flagged == False)
        .order_by(NodeComment.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, firebase_uid: str, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)
    comment = db.query(NodeComment).filter(NodeComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != user_uuid:
        raise HTTPException(status_code=403, detail="Cannot delete another user's comment")
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