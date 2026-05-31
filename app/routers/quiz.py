# app/routers/quiz.py
# End-of-trip Final Quiz. Questions are generated at runtime from the content of
# the nodes the user visited. The server stores the correct answers and grades
# answers (the client only reports its per-question timing), so gems can't be
# faked. One quiz per trip: once a session exists it can never be restarted, so
# quitting mid-quiz forfeits all provisional gems.

import math
import logging
from datetime import datetime, timezone

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
)
from app.services import gems
from app.services.quizgen import generate_quiz

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


@router.post("/start", response_model=QuizStartResponse)
async def start_quiz(firebase_uid: str, trip_id: int, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)

    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")

    # Anti re-entry: if a session already exists for this trip, never re-issue it.
    existing = db.query(QuizSession).filter(QuizSession.trip_id == trip_id).first()
    if existing:
        return QuizStartResponse(
            session_id=existing.id,
            status=existing.status,
            total_questions=existing.num_questions,
            gems_earned=existing.gems_earned or 0,
            questions=[],
            already_played=True,
        )

    site = db.query(HeritageSite).filter(HeritageSite.id == trip.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {trip.site_id} not found")

    # Visited nodes for this trip (recorded by /trips/end). Fall back to all
    # site nodes if the end-trip write hasn't landed yet (fire-and-forget race).
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

    generated = await generate_quiz(db, site, nodes)
    if not generated:
        raise HTTPException(status_code=503, detail="Could not generate quiz questions")

    session = QuizSession(
        user_id=user_uuid,
        trip_id=trip_id,
        site_id=site.id,
        status="active",
        num_questions=len(generated),
        gems_earned=0,
    )
    db.add(session)
    db.flush()  # get session.id

    for i, g in enumerate(generated):
        db.add(QuizQuestion(
            session_id=session.id,
            idx=i,
            question=g["question"],
            options=g["options"],
            correct_index=g["correct_index"],
            source_node_id=g.get("source_node_id"),
        ))
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
