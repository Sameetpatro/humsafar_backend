# app/routers/insights.py
#
# Per-site and per-node insight dashboards. Aggregates the raw signals we
# already collect (user_visit_history, node ratings, chat logs, comments) and
# trains a tiny linear model on the fly (see app/services/ml.py) to surface a
# couple of forward-looking numbers — predicted visitors tomorrow, minutes per
# extra spot explored, and an overall engagement score.

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import HeritageSite, Node, SiteInsightSnapshot, UserInsight
from app.routers.users import get_user_uuid
from app.schemas import (
    SiteInsightsResponse,
    NodeInsightsResponse,
    DailyVisit,
    NodePopularity,
    SiteMlInsight,
    NodeMlInsight,
    SiteInsightSnapshotResponse,
    UserInsightsResponse,
)
from app.services import ml

router = APIRouter(prefix="/insights", tags=["Insights"])

DAILY_WINDOW = 14   # days of history shown in the visits graph


def _persist_site_snapshot(db: Session, site_id: int, resp: SiteInsightsResponse) -> None:
    """Upsert today's insight snapshot for a site (idempotent per day)."""
    today = datetime.now(timezone.utc).date()
    ml_ = resp.ml
    row = (
        db.query(SiteInsightSnapshot)
        .filter(SiteInsightSnapshot.site_id == site_id, SiteInsightSnapshot.snapshot_date == today)
        .first()
    )
    if row is None:
        row = SiteInsightSnapshot(site_id=site_id, snapshot_date=today)
        db.add(row)
    row.total_visits                 = resp.total_visits
    row.unique_visitors              = resp.unique_visitors
    row.avg_duration_mins            = resp.avg_duration_mins
    row.avg_nodes_completed          = resp.avg_nodes_completed
    row.completion_rate              = resp.completion_rate
    row.total_interactions           = resp.total_interactions
    row.avg_rating                   = resp.avg_rating
    row.engagement_score             = ml_.engagement_score
    row.predicted_visits_next_day    = ml_.predicted_visits_next_day
    row.visits_trend                 = ml_.visits_trend
    row.mins_per_extra_node          = ml_.mins_per_extra_node
    row.predicted_full_duration_mins = ml_.predicted_full_duration_mins
    try:
        db.commit()
    except Exception:
        db.rollback()


def _mean(values):
    vals = [v for v in values if v is not None]
    return (sum(vals) / len(vals)) if vals else 0.0


@router.get("/sites/{site_id}", response_model=SiteInsightsResponse)
def site_insights(site_id: int, db: Session = Depends(get_db)):
    site = db.query(HeritageSite).filter(HeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")

    nodes = db.query(Node).filter(Node.site_id == site_id).order_by(Node.sequence_order).all()
    site_node_count = len(nodes)

    rows = db.execute(
        text("""
            SELECT user_id, duration_mins, nodes_completed, total_nodes,
                   nodes_visited, visited_at
            FROM user_visit_history
            WHERE site_id = :sid
        """),
        {"sid": site_id},
    ).fetchall()

    total_visits = len(rows)
    unique_visitors = len({str(r[0]) for r in rows})
    avg_duration = _mean([r[1] for r in rows])
    avg_nodes_completed = _mean([r[2] for r in rows])

    completion_ratios = [
        (r[2] or 0) / r[3] for r in rows if r[3] and r[3] > 0
    ]
    completion_rate = round(_mean(completion_ratios) * 100, 1)

    # AI interactions logged for this site (user-side messages)
    interactions = db.execute(
        text("SELECT COUNT(*) FROM user_chat_history WHERE site_id = :sid AND role = 'user'"),
        {"sid": site_id},
    ).scalar() or 0

    # ── Daily visits (last DAILY_WINDOW days) ─────────────────────────────────
    today = datetime.now(timezone.utc).date()
    counts = {today - timedelta(days=i): 0 for i in range(DAILY_WINDOW)}
    for r in rows:
        visited_at = r[5]
        if visited_at is None:
            continue
        d = visited_at.date()
        if d in counts:
            counts[d] += 1
    ordered_days = sorted(counts.keys())
    daily_visits = [
        DailyVisit(date=d.strftime("%m-%d"), count=counts[d]) for d in ordered_days
    ]

    # ── Node popularity (how many visits reached each node) ───────────────────
    node_popularity = []
    for node in nodes:
        node_visits = sum(1 for r in rows if r[4] and node.id in r[4])
        pop_pct = (node_visits / total_visits * 100) if total_visits else 0.0
        eng = ml.node_engagement_score(pop_pct, node.avg_rating or 0.0, 0, 0)
        node_popularity.append(NodePopularity(
            node_id=node.id,
            name=node.name,
            visits=node_visits,
            avg_rating=round(node.avg_rating or 0.0, 2),
            rating_count=node.rating_count or 0,
            engagement_score=eng,
        ))
    node_popularity.sort(key=lambda n: n.visits, reverse=True)

    # ── Tiny ML: train on the fly ─────────────────────────────────────────────
    ys = [dv.count for dv in daily_visits]
    xs = list(range(len(ys)))
    slope, intercept = ml.linear_regression(xs, ys)
    predicted_next = max(0, round(ml.predict(slope, intercept, len(ys))))
    trend = ml.trend_label(slope, scale=_mean(ys))

    dur_xs = [(r[2] or 0) for r in rows if r[1] is not None]
    dur_ys = [r[1] for r in rows if r[1] is not None]
    dslope, dintercept = ml.linear_regression(dur_xs, dur_ys)
    mins_per_node = round(dslope, 1)
    predicted_full = round(max(0.0, ml.predict(dslope, dintercept, site_node_count)), 1)

    interactions_per_visit = (interactions / total_visits) if total_visits else 0.0
    engagement = ml.site_engagement_score(
        completion_rate=completion_rate,
        avg_duration_mins=avg_duration,
        avg_rating=site.rating or 0.0,
        interactions_per_visit=interactions_per_visit,
    )

    if total_visits == 0:
        insight_text = "No visits recorded yet — insights will appear once explorers start their journey."
    else:
        insight_text = (
            f"Visitors explore about {avg_nodes_completed:.0f} of {site_node_count} spots "
            f"in ~{avg_duration:.0f} min. Engagement is {engagement:.0f}/100 and footfall is {trend}."
        )

    site_ml = SiteMlInsight(
        model="linear_regression",
        trained_on=total_visits,
        predicted_visits_next_day=predicted_next,
        visits_trend=trend,
        mins_per_extra_node=mins_per_node,
        predicted_full_duration_mins=predicted_full,
        engagement_score=engagement,
        insight_text=insight_text,
    )

    result = SiteInsightsResponse(
        site_id=site_id,
        site_name=site.name,
        total_visits=total_visits,
        unique_visitors=unique_visitors,
        avg_duration_mins=round(avg_duration, 1),
        avg_nodes_completed=round(avg_nodes_completed, 1),
        completion_rate=completion_rate,
        total_interactions=int(interactions),
        avg_rating=round(site.rating or 0.0, 2),
        daily_visits=daily_visits,
        node_popularity=node_popularity,
        ml=site_ml,
    )

    # Persist a daily snapshot so insight history accumulates for model training.
    _persist_site_snapshot(db, site_id, result)

    return result


@router.get("/sites/{site_id}/history", response_model=list[SiteInsightSnapshotResponse])
def site_insight_history(site_id: int, days: int = 90, db: Session = Depends(get_db)):
    """Stored daily insight snapshots for a site — the training-ready time series."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(1, days))
    rows = (
        db.query(SiteInsightSnapshot)
        .filter(SiteInsightSnapshot.site_id == site_id, SiteInsightSnapshot.snapshot_date >= cutoff)
        .order_by(SiteInsightSnapshot.snapshot_date.asc())
        .all()
    )
    return [
        SiteInsightSnapshotResponse(
            snapshot_date=r.snapshot_date.isoformat(),
            total_visits=r.total_visits or 0,
            unique_visitors=r.unique_visitors or 0,
            avg_duration_mins=round(r.avg_duration_mins or 0.0, 1),
            avg_nodes_completed=round(r.avg_nodes_completed or 0.0, 1),
            completion_rate=round(r.completion_rate or 0.0, 1),
            total_interactions=r.total_interactions or 0,
            avg_rating=round(r.avg_rating or 0.0, 2),
            engagement_score=round(r.engagement_score or 0.0, 1),
            predicted_visits_next_day=r.predicted_visits_next_day or 0,
            visits_trend=r.visits_trend or "steady",
            mins_per_extra_node=round(r.mins_per_extra_node or 0.0, 1),
            predicted_full_duration_mins=round(r.predicted_full_duration_mins or 0.0, 1),
        )
        for r in rows
    ]


@router.get("/nodes/{node_id}", response_model=NodeInsightsResponse)
def node_insights(node_id: int, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    site_id = node.site_id

    rows = db.execute(
        text("SELECT nodes_visited FROM user_visit_history WHERE site_id = :sid"),
        {"sid": site_id},
    ).fetchall()
    site_total_visits = len(rows)
    node_visits = sum(1 for r in rows if r[0] and node.id in r[0])
    popularity_pct = round((node_visits / site_total_visits * 100), 1) if site_total_visits else 0.0

    comments = db.execute(
        text("SELECT COUNT(*) FROM node_comments WHERE node_id = :nid AND is_flagged = false"),
        {"nid": node_id},
    ).scalar() or 0

    interactions = db.execute(
        text("SELECT COUNT(*) FROM user_chat_history WHERE node_id = :nid AND role = 'user'"),
        {"nid": node_id},
    ).scalar() or 0

    engagement = ml.node_engagement_score(
        popularity_pct=popularity_pct,
        avg_rating=node.avg_rating or 0.0,
        interactions=int(interactions),
        comments=int(comments),
    )

    if node_visits == 0:
        insight_text = "This spot hasn't been explored yet."
    else:
        insight_text = (
            f"{node_visits} of {site_total_visits} visitors reached this spot "
            f"({popularity_pct:.0f}%). Engagement {engagement:.0f}/100."
        )

    return NodeInsightsResponse(
        node_id=node_id,
        site_id=site_id,
        name=node.name,
        visits=node_visits,
        avg_rating=round(node.avg_rating or 0.0, 2),
        rating_count=node.rating_count or 0,
        comments=int(comments),
        interactions=int(interactions),
        popularity_pct=popularity_pct,
        ml=NodeMlInsight(engagement_score=engagement, insight_text=insight_text),
    )


def _explorer_level(total_visits: int, engagement: float) -> str:
    if total_visits >= 10 and engagement >= 60:
        return "Heritage Master"
    if total_visits >= 6:
        return "Trailblazer"
    if total_visits >= 3:
        return "Pathfinder"
    if total_visits >= 1:
        return "Explorer"
    return "Newcomer"


@router.get("/users/{firebase_uid}", response_model=UserInsightsResponse)
def user_insights(firebase_uid: str, db: Session = Depends(get_db)):
    """
    Personal heritage footprint for the signed-in user. Computes the metrics,
    trains a tiny per-user duration model, upserts the user_insights row, and
    returns it. This is the "my own insights" feed.
    """
    user_uuid = get_user_uuid(firebase_uid, db)

    rows = db.execute(
        text("""
            SELECT site_id, site_name, duration_mins, nodes_completed, total_nodes
            FROM user_visit_history
            WHERE user_id = :uid
        """),
        {"uid": str(user_uuid)},
    ).fetchall()

    total_visits = len(rows)
    sites_explored = len({r[0] for r in rows})
    durations = [r[2] for r in rows if r[2] is not None]
    total_duration = int(sum(durations))
    avg_duration = (total_duration / len(durations)) if durations else 0.0
    total_nodes_completed = int(sum((r[3] or 0) for r in rows))
    completion_ratios = [(r[3] or 0) / r[4] for r in rows if r[4] and r[4] > 0]
    avg_completion = round((sum(completion_ratios) / len(completion_ratios) * 100), 1) if completion_ratios else 0.0

    interactions = db.execute(
        text("""
            SELECT COUNT(*) FROM user_chat_history
            WHERE user_id = :uid AND role = 'user'
        """),
        {"uid": str(user_uuid)},
    ).scalar() or 0

    # Favourite site = most-visited
    fav_id, fav_name = None, None
    if rows:
        counts: dict = {}
        names: dict = {}
        for r in rows:
            counts[r[0]] = counts.get(r[0], 0) + 1
            names[r[0]] = r[1]
        fav_id = max(counts, key=counts.get)
        fav_name = names.get(fav_id)

    # Tiny per-user model: duration ~ nodes_completed → predict their next visit
    dur_xs = [(r[3] or 0) for r in rows if r[2] is not None]
    dur_ys = [r[2] for r in rows if r[2] is not None]
    dslope, dintercept = ml.linear_regression(dur_xs, dur_ys)
    avg_nodes = (sum(dur_xs) / len(dur_xs)) if dur_xs else 0.0
    predicted_next = round(max(0.0, ml.predict(dslope, dintercept, avg_nodes)), 1)

    interactions_per_visit = (interactions / total_visits) if total_visits else 0.0
    completion = ml.clamp(avg_completion, 0, 100) / 100.0
    duration_n = ml.clamp(avg_duration / 45.0, 0, 1)
    interaction_n = ml.clamp(interactions_per_visit / 6.0, 0, 1)
    engagement = round(ml.clamp((0.4 * completion + 0.3 * duration_n + 0.3 * interaction_n) * 100, 0, 100), 1)

    level = _explorer_level(total_visits, engagement)

    if total_visits == 0:
        insight_text = "Start exploring heritage sites to build your personal insights!"
    else:
        insight_text = (
            f"You've explored {sites_explored} site(s) across {total_visits} visit(s), "
            f"spending ~{avg_duration:.0f} min each. You're a {level} with an engagement of {engagement:.0f}/100."
        )

    # Upsert the user_insights row
    row = db.query(UserInsight).filter(UserInsight.user_id == user_uuid).first()
    if row is None:
        row = UserInsight(user_id=user_uuid)
        db.add(row)
    row.total_visits                 = total_visits
    row.sites_explored               = sites_explored
    row.total_duration_mins          = total_duration
    row.avg_duration_mins            = round(avg_duration, 1)
    row.total_nodes_completed        = total_nodes_completed
    row.avg_completion_rate          = avg_completion
    row.total_interactions           = int(interactions)
    row.favorite_site_id             = fav_id
    row.favorite_site_name           = fav_name
    row.engagement_score             = engagement
    row.explorer_level               = level
    row.predicted_next_duration_mins = predicted_next
    try:
        db.commit()
    except Exception:
        db.rollback()

    return UserInsightsResponse(
        user_id=str(user_uuid),
        total_visits=total_visits,
        sites_explored=sites_explored,
        total_duration_mins=total_duration,
        avg_duration_mins=round(avg_duration, 1),
        total_nodes_completed=total_nodes_completed,
        avg_completion_rate=avg_completion,
        total_interactions=int(interactions),
        favorite_site_id=fav_id,
        favorite_site_name=fav_name,
        engagement_score=engagement,
        explorer_level=level,
        predicted_next_duration_mins=predicted_next,
        insight_text=insight_text,
    )
