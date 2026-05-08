# app/routers/reviews.py
# UPGRADED:
#   - All user_id references now resolve firebase_uid → users.id (UUID FK)
#   - Rating averages updated transactionally in the same DB write (no trigger needed)
#   - Added POST /reviews/nodes/rate endpoint for per-node ratings
#   - analyzed_responses refreshed via upsert within submit_review (no async worker required at this scale;
#     swap for Celery task when row count exceeds ~50K reviews)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import Optional

from app.database import get_db
from app.models import HeritageSite, Node, SiteRating, NodeRating, TripReview, AnalyzedResponse
from app.routers.users import get_user_uuid
from app.schemas import (
    ReviewSubmitBody, ReviewSubmitResponse, ReviewSummaryResponse,
    NodeRatingRequest, NodeRatingResponse,
    SiteRatingRequest, SiteRatingResponse,
)

router = APIRouter(prefix="/reviews", tags=["Reviews"])


# ── Site star rating ──────────────────────────────────────────────────────────

@router.post("/sites/rate", response_model=SiteRatingResponse)
def rate_site(body: SiteRatingRequest, db: Session = Depends(get_db)):
    if not 1 <= body.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    user_uuid = get_user_uuid(body.firebase_uid, db)

    site = db.query(HeritageSite).filter(HeritageSite.id == body.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Upsert rating
    db.execute(
        text("""
            INSERT INTO site_ratings (site_id, user_id, rating, updated_at)
            VALUES (:site_id, :user_id, :rating, now())
            ON CONFLICT (site_id, user_id) DO UPDATE SET rating = :rating, updated_at = now()
        """),
        {"site_id": body.site_id, "user_id": str(user_uuid), "rating": body.rating}
    )

    # Recalculate avg and write back — same transaction, no trigger needed
    result = db.execute(
        text("SELECT COALESCE(AVG(rating), 0)::float, COUNT(*) FROM site_ratings WHERE site_id = :sid"),
        {"sid": body.site_id}
    ).fetchone()
    new_avg, total = float(result[0]), int(result[1])

    db.execute(
        text("UPDATE heritage_sites SET rating = :avg WHERE id = :sid"),
        {"avg": new_avg, "sid": body.site_id}
    )
    db.commit()

    return SiteRatingResponse(message="Rating saved", new_avg=round(new_avg, 2), total=total)


# ── Node star rating ──────────────────────────────────────────────────────────

@router.post("/nodes/rate", response_model=NodeRatingResponse)
def rate_node(body: NodeRatingRequest, db: Session = Depends(get_db)):
    if not 1 <= body.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    user_uuid = get_user_uuid(body.firebase_uid, db)

    node = db.query(Node).filter(Node.id == body.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Upsert node rating
    db.execute(
        text("""
            INSERT INTO node_ratings (node_id, site_id, user_id, rating, updated_at)
            VALUES (:node_id, :site_id, :user_id, :rating, now())
            ON CONFLICT (node_id, user_id) DO UPDATE SET rating = :rating, updated_at = now()
        """),
        {
            "node_id": body.node_id,
            "site_id": body.site_id,
            "user_id": str(user_uuid),
            "rating": body.rating,
        }
    )

    # Update denormalized avg_rating and rating_count on nodes row
    result = db.execute(
        text("SELECT COALESCE(AVG(rating), 0)::float, COUNT(*) FROM node_ratings WHERE node_id = :nid"),
        {"nid": body.node_id}
    ).fetchone()
    new_avg, total = float(result[0]), int(result[1])

    db.execute(
        text("UPDATE nodes SET avg_rating = :avg, rating_count = :cnt WHERE id = :nid"),
        {"avg": new_avg, "cnt": total, "nid": body.node_id}
    )
    db.commit()

    return NodeRatingResponse(message="Node rating saved", new_avg=round(new_avg, 2), total=total)


# ── Trip review (post-visit survey) ──────────────────────────────────────────

@router.post("/submit", response_model=ReviewSubmitResponse)
def submit_review(body: ReviewSubmitBody, db: Session = Depends(get_db)):
    for val, label in [(body.star_rating, "star_rating"), (body.q1, "q1"), (body.q2, "q2"), (body.q3, "q3")]:
        if not 1 <= val <= 5:
            raise HTTPException(status_code=400, detail=f"{label} must be between 1 and 5")

    user_uuid = get_user_uuid(body.firebase_uid, db)

    site = db.query(HeritageSite).filter(HeritageSite.id == body.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # 1. Upsert site star rating
    db.execute(
        text("""
            INSERT INTO site_ratings (site_id, user_id, rating, updated_at)
            VALUES (:site_id, :user_id, :rating, now())
            ON CONFLICT (site_id, user_id) DO UPDATE SET rating = :rating, updated_at = now()
        """),
        {"site_id": body.site_id, "user_id": str(user_uuid), "rating": body.star_rating}
    )

    # 2. Upsert trip review
    db.execute(
        text("""
            INSERT INTO trip_reviews
                (trip_id, site_id, user_id, q1_overall_experience, q2_guide_helpfulness,
                 q3_recommend_to_others, suggestion_text)
            VALUES (:trip_id, :site_id, :user_id, :q1, :q2, :q3, :suggestion)
            ON CONFLICT (trip_id) DO UPDATE SET
                q1_overall_experience  = EXCLUDED.q1_overall_experience,
                q2_guide_helpfulness   = EXCLUDED.q2_guide_helpfulness,
                q3_recommend_to_others = EXCLUDED.q3_recommend_to_others,
                suggestion_text        = EXCLUDED.suggestion_text,
                submitted_at           = now()
        """),
        {
            "trip_id": body.trip_id, "site_id": body.site_id, "user_id": str(user_uuid),
            "q1": body.q1, "q2": body.q2, "q3": body.q3, "suggestion": body.suggestion_text,
        }
    )

    # 3. Recalculate avg rating → write to heritage_sites (no trigger)
    r = db.execute(
        text("SELECT COALESCE(AVG(rating), 0)::float FROM site_ratings WHERE site_id = :sid"),
        {"sid": body.site_id}
    ).fetchone()
    new_avg = float(r[0])
    db.execute(
        text("UPDATE heritage_sites SET rating = :avg WHERE id = :sid"),
        {"avg": new_avg, "sid": body.site_id}
    )

    # 4. Refresh analyzed_responses inline (fast at small scale; move to Celery at 50K+ reviews)
    _refresh_analyzed(db, body.site_id)

    # 5. Mark visit history review_submitted.
    #    If /trips/end hasn't landed yet (slow network, fire-and-forget races),
    #    a plain UPDATE silently no-ops. Upsert a minimal row instead so the
    #    review submission is never lost — /trips/end's later ON CONFLICT
    #    will fill in the timing/visited fields without resetting this flag.
    trip_row = db.execute(
        text("SELECT site_id, started_at FROM trips WHERE id = :tid"),
        {"tid": body.trip_id},
    ).fetchone()

    if trip_row is None:
        # Should never happen — the FK on trip_reviews already enforced this —
        # but guard so the route degrades to "review saved, history pending".
        pass
    else:
        site_for_history = db.query(HeritageSite).filter(HeritageSite.id == trip_row[0]).first()
        site_name_hist   = site_for_history.name if site_for_history else "Unknown"
        started_at       = trip_row[1]
        total_nodes_hist = db.query(Node).filter(Node.site_id == trip_row[0]).count()

        db.execute(
            text("""
                INSERT INTO user_visit_history
                    (user_id, site_id, trip_id, site_name,
                     total_nodes, completed, visited_at, review_submitted)
                VALUES
                    (:user_id, :site_id, :trip_id, :site_name,
                     :total_nodes, true, :visited_at, true)
                ON CONFLICT (user_id, trip_id) DO UPDATE SET
                    review_submitted = true
            """),
            {
                "user_id":     str(user_uuid),
                "site_id":     trip_row[0],
                "trip_id":     body.trip_id,
                "site_name":   site_name_hist,
                "total_nodes": total_nodes_hist,
                "visited_at":  started_at,
            },
        )

    db.commit()

    rev_row = db.execute(
        text("SELECT id FROM trip_reviews WHERE trip_id = :tid"), {"tid": body.trip_id}
    ).fetchone()
    review_id = rev_row[0] if rev_row else 0

    return ReviewSubmitResponse(message="Review submitted", review_id=review_id, new_rating=round(new_avg, 2))


def _refresh_analyzed(db: Session, site_id: int):
    """
    Recalculate and upsert analyzed_responses for a site.
    Called synchronously inside submit_review at low scale.
    At high scale, replace with: celery_worker.refresh_analyzed.delay(site_id)
    """
    r = db.execute(
        text("""
            SELECT
                COALESCE(AVG(sr.rating), 0)::float          AS avg_star,
                COUNT(sr.id)                                 AS total_ratings,
                COALESCE(AVG(tr.q1_overall_experience), 0)  AS avg_q1,
                COALESCE(AVG(tr.q2_guide_helpfulness), 0)   AS avg_q2,
                COALESCE(AVG(tr.q3_recommend_to_others), 0) AS avg_q3,
                COUNT(tr.id)                                 AS total_reviews,
                CASE WHEN COUNT(tr.id) > 0
                     THEN 100.0 * SUM(CASE WHEN tr.q3_recommend_to_others >= 4 THEN 1 ELSE 0 END)::float / COUNT(tr.id)
                     ELSE 0 END                             AS recommend_pct
            FROM heritage_sites hs
            LEFT JOIN site_ratings  sr ON sr.site_id = hs.id
            LEFT JOIN trip_reviews  tr ON tr.site_id = hs.id
            WHERE hs.id = :sid
        """),
        {"sid": site_id}
    ).fetchone()

    avg_q1 = float(r[2])
    label = (
        "Excellent" if avg_q1 >= 4.5 else
        "Good"      if avg_q1 >= 4.0 else
        "Average"   if avg_q1 >= 3.0 else
        "Poor"      if r[5] > 0      else
        "No data"
    )

    db.execute(
        text("""
            INSERT INTO analyzed_responses
                (site_id, avg_star_rating, total_ratings, avg_overall_experience,
                 avg_guide_helpfulness, avg_recommend_score, total_reviews,
                 recommend_pct, satisfaction_label, last_updated)
            VALUES (:sid, :avg_star, :total_r, :avg_q1, :avg_q2, :avg_q3,
                    :total_rev, :rec_pct, :label, now())
            ON CONFLICT (site_id) DO UPDATE SET
                avg_star_rating        = EXCLUDED.avg_star_rating,
                total_ratings          = EXCLUDED.total_ratings,
                avg_overall_experience = EXCLUDED.avg_overall_experience,
                avg_guide_helpfulness  = EXCLUDED.avg_guide_helpfulness,
                avg_recommend_score    = EXCLUDED.avg_recommend_score,
                total_reviews          = EXCLUDED.total_reviews,
                recommend_pct          = EXCLUDED.recommend_pct,
                satisfaction_label     = EXCLUDED.satisfaction_label,
                last_updated           = now()
        """),
        {
            "sid": site_id, "avg_star": float(r[0]), "total_r": int(r[1]),
            "avg_q1": float(r[2]), "avg_q2": float(r[3]), "avg_q3": float(r[4]),
            "total_rev": int(r[5]), "rec_pct": float(r[6]), "label": label,
        }
    )


# ── Analytics summary ─────────────────────────────────────────────────────────

@router.get("/sites/{site_id}/summary", response_model=ReviewSummaryResponse)
def get_site_review_summary(site_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            SELECT avg_star_rating, total_ratings, avg_overall_experience, avg_guide_helpfulness,
                   avg_recommend_score, total_reviews, recommend_pct, satisfaction_label
            FROM analyzed_responses WHERE site_id = :sid
        """),
        {"site_id": site_id}
    ).fetchone()

    if not row:
        return ReviewSummaryResponse(
            avg_star_rating=0.0, total_ratings=0, avg_overall_experience=0.0,
            avg_guide_helpfulness=0.0, avg_recommend_score=0.0,
            total_reviews=0, recommend_pct=0.0, satisfaction_label="No data",
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


# ── User visit history ────────────────────────────────────────────────────────

@router.get("/users/{firebase_uid}/history")
def get_user_visit_history(firebase_uid: str, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)

    rows = db.execute(
        text("""
            SELECT uvh.id, uvh.site_id, uvh.site_name, uvh.trip_id, uvh.nodes_visited,
                   uvh.total_nodes, uvh.nodes_completed, uvh.completed,
                   uvh.visited_at, uvh.ended_at, uvh.duration_mins, uvh.review_submitted
            FROM user_visit_history uvh
            WHERE uvh.user_id = :user_id
            ORDER BY uvh.visited_at DESC
        """),
        {"user_id": str(user_uuid)}
    ).fetchall()

    return [
        {
            "id": r[0], "site_id": r[1], "site_name": r[2], "trip_id": r[3],
            "nodes_visited": list(r[4]) if r[4] else [],
            "total_nodes": r[5], "nodes_completed": r[6], "completed": r[7],
            "visited_at": r[8].isoformat() if r[8] else None,
            "ended_at": r[9].isoformat() if r[9] else None,
            "duration_mins": r[10], "review_submitted": r[11],
        }
        for r in rows
    ]