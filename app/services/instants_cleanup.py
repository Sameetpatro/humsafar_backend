# app/services/instants_cleanup.py
# Retention policy for node instants:
#   • Each instant lives at most 34 hours (by created_at).
#   • At most 50 instants per node survive — ranked by likes, then recency.
#     Anything outside the top 50 is removed after expiry cleanup.

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import NodeInstant

logger = logging.getLogger(__name__)

INSTANT_TTL_HOURS = 34
MAX_INSTANTS_PER_NODE = 50


def instant_expiry_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=INSTANT_TTL_HOURS)


def cleanup_node_instants(db: Session, node_id: int) -> int:
    """
    Enforce TTL + top-50 cap for one node. Returns number of rows deleted.
    Likes cascade-delete via FK. Firebase blobs are not removed here (DB only).
    """
    cutoff = instant_expiry_cutoff()
    deleted = 0

    expired = (
        db.query(NodeInstant)
        .filter(NodeInstant.node_id == node_id, NodeInstant.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    deleted += expired

    keep_rows = db.execute(
        text("""
            SELECT id FROM node_instants
            WHERE node_id = :nid
              AND is_flagged = FALSE
              AND created_at >= :cutoff
            ORDER BY like_count DESC, created_at DESC
            LIMIT :lim
        """),
        {"nid": node_id, "cutoff": cutoff, "lim": MAX_INSTANTS_PER_NODE},
    ).fetchall()
    keep_ids = [r.id for r in keep_rows]

    if keep_ids:
        overflow = (
            db.query(NodeInstant)
            .filter(
                NodeInstant.node_id == node_id,
                NodeInstant.is_flagged.is_(False),
                ~NodeInstant.id.in_(keep_ids),
            )
            .delete(synchronize_session=False)
        )
        deleted += overflow
    else:
        overflow = (
            db.query(NodeInstant)
            .filter(
                NodeInstant.node_id == node_id,
                NodeInstant.is_flagged.is_(False),
            )
            .delete(synchronize_session=False)
        )
        deleted += overflow

    if deleted:
        db.commit()
        logger.info(f"[instants] node_id={node_id} cleanup removed {deleted} row(s)")

    return deleted


def cleanup_all_nodes(db: Session) -> int:
    """Run retention on every node that has instants. Useful for periodic sweeps."""
    node_ids = [
        r[0]
        for r in db.query(NodeInstant.node_id).distinct().all()
    ]
    total = 0
    for nid in node_ids:
        total += cleanup_node_instants(db, nid)
    return total
