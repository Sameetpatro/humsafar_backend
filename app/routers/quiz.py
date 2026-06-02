# app/routers/quiz.py
# End-of-trip Final Quiz. Questions are generated incrementally while the user
# explores (POST /quiz/prepare after each node scan — 7 questions per node).
# At trip end, POST /quiz/start activates the prepared session instantly.

import math
import logging
from datetime import datetime, timezone
from typing import List, Set

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.database import get_db
from app.models import Trip, HeritageSite, Node, QuizSession, QuizQuestion
from app.routers.users import get_user_uuid
from app.schemas import (
    QuizStartResponse,
    QuizQuestionPublic,
    QuizAnswerRequest,
    QuizAnswerResponse,
    QuizCompleteRequest,
    QuizCompleteResponse,
    QuizAbandonRequest,
    QuizPrepareRequest,
    QuizPrepareResponse,
)
from app.services import gems
from app.services.quizgen import generate_quiz, generate_questions_for_node, QUESTIONS_PER_NODE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quiz", tags=["Quiz"])

SECONDS_PER_QUESTION = 10
MAX_GEMS_PER_QUESTION = 10


def _gems_for(seconds_taken: float, is_correct: bool) -> int:
    """gems = max(0, 10 - floor(seconds)); 0 if wrong or timed out (>=10s)."""
    if not is_correct:
        return 0
    if seconds_taken is None or seconds_taken >= SECONDS_PER_QUESTION:
        return 0
    return max(0, MAX_GEMS_PER_QUESTION - int(math.floor(max(0.0, seconds_taken))))


def _public_questions(session: QuizSession) -> list:
    return [
        QuizQuestionPublic(
            question_id=q.id,
            idx=q.idx,
            question=q.question,
            options=list(q.options or []),
            answered=bool(q.answered),
        )
        for q in sorted(session.questions, key=lambda x: x.idx)
    ]


def _nodes_with_questions(session: QuizSession) -> Set[int]:
    return {q.source_node_id for q in session.questions if q.source_node_id is not None}


def _get_or_create_preparing_session(
    db: Session, user_uuid, trip: Trip, site: HeritageSite
) -> QuizSession:
    existing = db.query(QuizSession).filter(QuizSession.trip_id == trip.id).first()
    if existing:
        return existing
    session = QuizSession(
        user_id=user_uuid,
        trip_id=trip.id,
        site_id=site.id,
        status="preparing",
        num_questions=0,
        gems_earned=0,
    )
    db.add(session)
    db.flush()
    return session


async def _append_questions_for_nodes(
    db: Session,
    session: QuizSession,
    site: HeritageSite,
    node_ids: List[int],
) -> int:
    """Generate questions for nodes not yet covered. Returns count of nodes prepared."""
    if session.status in ("completed", "abandoned"):
        return 0

    already = _nodes_with_questions(session)
    to_prepare = [nid for nid in node_ids if nid not in already]
    if not to_prepare:
        return 0

    nodes = db.query(Node).filter(Node.id.in_(to_prepare), Node.site_id == site.id).all()
    node_by_id = {n.id: n for n in nodes}
    prepared = 0
    next_idx = len(session.questions)

    for nid in to_prepare:
        node = node_by_id.get(nid)
        if not node:
            continue
        generated = await generate_questions_for_node(db, site, node, QUESTIONS_PER_NODE)
        if not generated:
            continue
        for g in generated:
            db.add(QuizQuestion(
                session_id=session.id,
                idx=next_idx,
                question=g["question"],
                options=g["options"],
                correct_index=g["correct_index"],
                source_node_id=g.get("source_node_id"),
            ))
            next_idx += 1
        prepared += 1

    session.num_questions = next_idx
    if session.status == "preparing" and next_idx > 0:
        session.status = "preparing"
    db.commit()
    db.refresh(session)
    return prepared


@router.post("/prepare", response_model=QuizPrepareResponse)
async def prepare_quiz(
    firebase_uid: str,
    trip_id:      int,
    payload:      QuizPrepareRequest,
    db: Session = Depends(get_db),
):
    """
    Incrementally build the quiz while the user is still on their trip.
    Call after every node scan with the full list of visited node ids.
    Generates 7 questions per newly visited node.
    """
    user_uuid = get_user_uuid(firebase_uid, db)
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")
    if trip.user_id is not None and trip.user_id != user_uuid:
        raise HTTPException(status_code=403, detail="Not your trip")

    site = db.query(HeritageSite).filter(HeritageSite.id == trip.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {trip.site_id} not found")

    existing = db.query(QuizSession).filter(QuizSession.trip_id == trip_id).first()
    if existing and existing.status in ("completed", "abandoned"):
        return QuizPrepareResponse(
            session_id=existing.id,
            status=existing.status,
            total_questions=existing.num_questions or 0,
            nodes_prepared=0,
        )

    session = _get_or_create_preparing_session(db, user_uuid, trip, site)
    db.commit()

    node_ids = list(dict.fromkeys(payload.node_ids))  # preserve order, dedupe
    prepared = await _append_questions_for_nodes(db, session, site, node_ids)

    return QuizPrepareResponse(
        session_id=session.id,
        status=session.status,
        total_questions=session.num_questions or 0,
        nodes_prepared=prepared,
    )


@router.post("/start", response_model=QuizStartResponse)
async def start_quiz(firebase_uid: str, trip_id: int, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)

    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")

    existing = db.query(QuizSession).filter(QuizSession.trip_id == trip_id).first()
    if existing:
        if existing.status in ("completed", "abandoned"):
            return QuizStartResponse(
                session_id=existing.id,
                status=existing.status,
                total_questions=existing.num_questions,
                gems_earned=existing.gems_earned or 0,
                questions=[],
                already_played=True,
            )
        # Prepared or active session — activate and return cached questions.
        if existing.questions:
            if existing.status == "preparing":
                existing.status = "active"
                db.commit()
                db.refresh(existing)
            return QuizStartResponse(
                session_id=existing.id,
                status=existing.status,
                seconds_per_question=SECONDS_PER_QUESTION,
                total_questions=existing.num_questions,
                gems_earned=existing.gems_earned or 0,
                questions=_public_questions(existing),
                already_played=False,
            )

    site = db.query(HeritageSite).filter(HeritageSite.id == trip.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {trip.site_id} not found")

    # Fallback: build quiz at end-trip if prepare was never called.
    visited_ids = db.execute(
        sql_text("""
            SELECT nodes_visited FROM user_visit_history
            WHERE user_id = :uid AND trip_id = :tid
        """),
        {"uid": str(user_uuid), "tid": trip_id},
    ).scalar()
    if visited_ids:
        nodes = db.query(Node).filter(Node.id.in_(list(visited_ids))).all()
    else:
        nodes = []
    if not nodes:
        nodes = db.query(Node).filter(Node.site_id == site.id).order_by(Node.sequence_order).all()
    if not nodes:
        raise HTTPException(status_code=400, detail="No nodes available to build a quiz")

    session = _get_or_create_preparing_session(db, user_uuid, trip, site)
    db.commit()
    await _append_questions_for_nodes(db, session, site, [n.id for n in nodes])

    db.refresh(session)
    if not session.questions:
        generated = await generate_quiz(db, site, nodes)
        if not generated:
            raise HTTPException(status_code=503, detail="Could not generate quiz questions")
        for i, g in enumerate(generated):
            db.add(QuizQuestion(
                session_id=session.id,
                idx=i,
                question=g["question"],
                options=g["options"],
                correct_index=g["correct_index"],
                source_node_id=g.get("source_node_id"),
            ))
        session.num_questions = len(generated)

    session.status = "active"
    db.commit()
    db.refresh(session)

    return QuizStartResponse(
        session_id=session.id,
        status=session.status,
        seconds_per_question=SECONDS_PER_QUESTION,
        total_questions=session.num_questions,
        gems_earned=0,
        questions=_public_questions(session),
        already_played=False,
    )


@router.post("/answer", response_model=QuizAnswerResponse)
def answer_quiz(req: QuizAnswerRequest, db: Session = Depends(get_db)):
    session = db.query(QuizSession).filter(QuizSession.id == req.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Quiz session not found")
    if session.status != "active":
        raise HTTPException(status_code=409, detail=f"Quiz is {session.status}")

    q = db.query(QuizQuestion).filter(
        QuizQuestion.id == req.question_id,
        QuizQuestion.session_id == session.id,
    ).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found in this session")

    # Idempotent — re-answering returns the original result.
    if q.answered:
        return QuizAnswerResponse(
            correct=q.is_correct,
            correct_index=q.correct_index,
            gems_awarded=q.gems_awarded or 0,
            running_total=session.gems_earned or 0,
        )

    is_correct = req.selected_index == q.correct_index
    awarded = _gems_for(req.seconds_taken, is_correct)

    q.answered = True
    q.selected_index = req.selected_index
    q.seconds_taken = req.seconds_taken
    q.is_correct = is_correct
    q.gems_awarded = awarded
    session.gems_earned = (session.gems_earned or 0) + awarded
    db.commit()

    return QuizAnswerResponse(
        correct=is_correct,
        correct_index=q.correct_index,
        gems_awarded=awarded,
        running_total=session.gems_earned or 0,
    )


@router.post("/complete", response_model=QuizCompleteResponse)
def complete_quiz(req: QuizCompleteRequest, db: Session = Depends(get_db)):
    session = db.query(QuizSession).filter(QuizSession.id == req.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Quiz session not found")

    if session.status == "completed":
        return QuizCompleteResponse(
            status="completed",
            gems_earned=session.gems_earned or 0,
            new_balance=gems.get_balance(db, session.user_id),
        )
    if session.status == "abandoned":
        return QuizCompleteResponse(
            status="abandoned",
            gems_earned=0,
            new_balance=gems.get_balance(db, session.user_id),
        )

    earned = session.gems_earned or 0
    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    # Credit gems in the same transaction as the status change.
    new_balance = gems.get_balance(db, session.user_id)
    if earned > 0:
        new_balance = gems.credit(db, session.user_id, earned, reason="quiz",
                                  ref_id=str(session.id), commit=False)
    db.commit()

    return QuizCompleteResponse(status="completed", gems_earned=earned, new_balance=new_balance)


@router.post("/abandon")
def abandon_quiz(req: QuizAbandonRequest, db: Session = Depends(get_db)):
    session = db.query(QuizSession).filter(QuizSession.id == req.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Quiz session not found")
    if session.status == "active":
        session.status = "abandoned"
        session.gems_earned = 0
        session.completed_at = datetime.now(timezone.utc)
        db.commit()
    return {"status": session.status, "gems_earned": 0}
