# app/routers/reviews.py
# Dharohar Setu — review submission and site summary

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import HeritageSite

router = APIRouter(prefix="/reviews", tags=["Reviews"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ReviewSubmitBody(BaseModel):
    trip_id: int
    site_id: int
    user_id: str
    star_rating: int  # 1–5
    q1: int  # q1_overall_experience 1–5
    q2: int  # q2_guide_helpfulness 1–5
    q3: int  # q3_recommend_to_others 1–5
    suggestion_text: Optional[str] = None


class ReviewSubmitResponse(BaseModel):
    message: str
    review_id: int
    new_rating: float


class ReviewSummaryResponse(BaseModel):
    avg_star_rating: float
    total_ratings: int
    avg_overall_experience: float
    avg_guide_helpfulness: float
    avg_recommend_score: float
    total_reviews: int
    recommend_pct: float
    satisfaction_label: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/submit", response_model=ReviewSubmitResponse)
def submit_review(body: ReviewSubmitBody, db: Session = Depends(get_db)):
    if not (1 <= body.star_rating <= 5 and 1 <= body.q1 <= 5 and 1 <= body.q2 <= 5 and 1 <= body.q3 <= 5):
        raise HTTPException(status_code=400, detail="All ratings must be between 1 and 5")

    site = db.query(HeritageSite).filter(HeritageSite.id == body.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Upsert site_ratings
    db.execute(
        text("""
            INSERT INTO site_ratings (site_id, user_id, rating, updated_at)
            VALUES (:site_id, :user_id, :rating, now())
            ON CONFLICT (site_id, user_id) DO UPDATE SET rating = :rating, updated_at = now()
        """),
        {"site_id": body.site_id, "user_id": body.user_id, "rating": body.star_rating}
    )

    # Insert or replace trip_reviews (UNIQUE on trip_id)
    db.execute(
        text("""
            INSERT INTO trip_reviews (trip_id, site_id, user_id, q1_overall_experience, q2_guide_helpfulness, q3_recommend_to_others, suggestion_text)
            VALUES (:trip_id, :site_id, :user_id, :q1, :q2, :q3, :suggestion)
            ON CONFLICT (trip_id) DO UPDATE SET
                site_id = EXCLUDED.site_id,
                user_id = EXCLUDED.user_id,
                q1_overall_experience = EXCLUDED.q1_overall_experience,
                q2_guide_helpfulness = EXCLUDED.q2_guide_helpfulness,
                q3_recommend_to_others = EXCLUDED.q3_recommend_to_others,
                suggestion_text = EXCLUDED.suggestion_text,
                submitted_at = now()
        """),
        {
            "trip_id": body.trip_id,
            "site_id": body.site_id,
            "user_id": body.user_id,
            "q1": body.q1,
            "q2": body.q2,
            "q3": body.q3,
            "suggestion": body.suggestion_text,
        }
    )

    # Mark user_visit_history.review_submitted = true
    db.execute(
        text("""
            UPDATE user_visit_history
            SET review_submitted = true
            WHERE trip_id = :trip_id AND user_id = :user_id
        """),
        {"trip_id": body.trip_id, "user_id": body.user_id}
    )

    db.commit()

    # Get new avg rating and review id
    row = db.execute(text("SELECT rating FROM heritage_sites WHERE id = :id"), {"id": body.site_id}).fetchone()
    new_rating = float(row[0]) if row else 0.0

    rev_row = db.execute(text("SELECT id FROM trip_reviews WHERE trip_id = :tid"), {"tid": body.trip_id}).fetchone()
    review_id = rev_row[0] if rev_row else 0

    return ReviewSubmitResponse(
        message="Review submitted",
        review_id=review_id,
        new_rating=new_rating,
    )


@router.get("/sites/{site_id}/summary", response_model=ReviewSummaryResponse)
def get_site_review_summary(site_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            SELECT avg_star_rating, total_ratings, avg_overall_experience, avg_guide_helpfulness,
                   avg_recommend_score, total_reviews, recommend_pct, satisfaction_label
            FROM analyzed_responses
            WHERE site_id = :site_id
        """),
        {"site_id": site_id}
    ).fetchone()

    if not row:
        return ReviewSummaryResponse(
            avg_star_rating=0.0,
            total_ratings=0,
            avg_overall_experience=0.0,
            avg_guide_helpfulness=0.0,
            avg_recommend_score=0.0,
            total_reviews=0,
            recommend_pct=0.0,
            satisfaction_label="No data",
        )

    return ReviewSummaryResponse(
        avg_star_rating=float(row[0] or 0),
        total_ratings=int(row[1] or 0),
        avg_overall_experience=float(row[2] or 0),
        avg_guide_helpfulness=float(row[3] or 0),
        avg_recommend_score=float(row[4] or 0),
        total_reviews=int(row[5] or 0),
        recommend_pct=float(row[6] or 0),
        satisfaction_label=str(row[7] or "No data"),
    )


@router.get("/users/{user_id}/history")
def get_user_visit_history(user_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text("""
            SELECT uvh.id, uvh.site_id, uvh.site_name, uvh.trip_id, uvh.nodes_visited,
                   uvh.total_nodes, uvh.nodes_completed, uvh.completed,
                   uvh.visited_at, uvh.ended_at, uvh.duration_mins, uvh.review_submitted
            FROM user_visit_history uvh
            WHERE uvh.user_id = :user_id
            ORDER BY uvh.visited_at DESC
        """),
        {"user_id": user_id}
    ).fetchall()

    return [
        {
            "id": r[0],
            "site_id": r[1],
            "site_name": r[2],
            "trip_id": r[3],
            "nodes_visited": list(r[4]) if r[4] else [],
            "total_nodes": r[5],
            "nodes_completed": r[6],
            "completed": r[7],
            "visited_at": r[8].isoformat() if r[8] else None,
            "ended_at": r[9].isoformat() if r[9] else None,
            "duration_mins": r[10],
            "review_submitted": r[11],
        }
        for r in rows
    ]
