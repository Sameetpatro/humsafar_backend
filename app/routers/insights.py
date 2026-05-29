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
from app.models import HeritageSite, Node
from app.schemas import (
    SiteInsightsResponse,
    NodeInsightsResponse,
    DailyVisit,
    NodePopularity,
    SiteMlInsight,
    NodeMlInsight,
)
from app.services import ml

router = APIRouter(prefix="/insights", tags=["Insights"])

DAILY_WINDOW = 14   # days of history shown in the visits graph


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

    return SiteInsightsResponse(
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
