# app/services/quizgen.py
# Builds heritage quiz questions at runtime from the content of the nodes the
# user actually visited (plus site-level summary/history/fun_facts). Uses the
# existing OpenRouter LLM; falls back to a couple of template questions if the
# model is unavailable or returns unparseable output, so the quiz never blocks.

import json
import logging
import random
import re
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import HeritageSite, Node, Prompt
from app.services.openrouter import call_openrouter

logger = logging.getLogger(__name__)

MIN_QUESTIONS = 5
MAX_QUESTIONS = 8
QUESTIONS_PER_NODE = 7


def _node_context(db: Session, node: Node) -> str:
    parts = [f"Spot: {node.name}"]
    if node.description:
        parts.append(node.description)
    prompt = (
        db.query(Prompt)
        .filter(Prompt.site_id == node.site_id, Prompt.node_id == node.id)
        .first()
    )
    if prompt and prompt.content:
        parts.append(prompt.content)
    return "\n".join(parts)


def _build_source_text(db: Session, site: HeritageSite, nodes: List[Node]) -> str:
    parts = [f"Heritage site: {site.name}"]
    if site.summary:
        parts.append(f"Summary: {site.summary}")
    if site.history:
        parts.append(f"History: {site.history}")
    if site.fun_facts:
        parts.append(f"Fun facts: {site.fun_facts}")
    for node in nodes:
        ctx = _node_context(db, node)
        if ctx:
            parts.append("\n" + ctx)
    return "\n".join(parts)


def _coerce_json(raw: str):
    """Pull a JSON array out of an LLM reply that may be fenced or chatty."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def _normalize(items, nodes: List[Node]) -> List[dict]:
    """Validate + clamp LLM output into well-formed 4-option MCQs."""
    node_ids = [n.id for n in nodes]
    out: List[dict] = []
    for it in items:
        try:
            q = str(it["question"]).strip()
            opts = [str(o).strip() for o in it["options"] if str(o).strip()]
            ci = int(it["correct_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if not q or len(opts) < 2 or ci < 0 or ci >= len(opts):
            continue
        opts = opts[:4]
        if ci >= len(opts):
            continue
        src = it.get("source_node_id")
        if src not in node_ids:
            src = node_ids[0] if node_ids else None
        out.append({
            "question": q,
            "options": opts,
            "correct_index": ci,
            "source_node_id": src,
        })
    return out


def _fallback_questions(site: HeritageSite, nodes: List[Node]) -> List[dict]:
    """Deterministic template questions so the quiz works even offline."""
    questions: List[dict] = []
    names = [n.name for n in nodes if n.name]
    if names:
        correct = names[0]
        distractors = ["A nearby market", "A modern museum", "A railway station"]
        options = [correct] + distractors[:3]
        random.shuffle(options)
        questions.append({
            "question": f"Which of these is a spot you explored at {site.name}?",
            "options": options,
            "correct_index": options.index(correct),
            "source_node_id": nodes[0].id,
        })
    questions.append({
        "question": f"What kind of place is {site.name}?",
        "options": ["A heritage site", "A shopping mall", "An airport", "A hospital"],
        "correct_index": 0,
        "source_node_id": nodes[0].id if nodes else None,
    })
    return questions


async def generate_quiz(db: Session, site: HeritageSite, nodes: List[Node]) -> List[dict]:
    """
    Returns a list of {question, options, correct_index, source_node_id}.
    Targets 5-8 questions derived from the visited nodes' content.
    """
    target = max(MIN_QUESTIONS, min(MAX_QUESTIONS, len(nodes) + 4))
    source_text = _build_source_text(db, site, nodes)

    system_prompt = (
        "You are a quiz master for a heritage tourism app. Using ONLY the heritage "
        "context provided, write engaging multiple-choice questions a visitor could "
        "answer after their tour. Each question has exactly 4 options with exactly one "
        "correct answer. Keep questions concise and factual; do not invent facts that "
        "are not supported by the context. Return STRICT JSON: an array of objects with "
        "keys \"question\" (string), \"options\" (array of 4 strings), \"correct_index\" "
        "(0-3 integer), and \"source_node_id\" (integer node id this question is about). "
        "Do not include any text outside the JSON array."
    )
    node_index = "\n".join(f"node_id={n.id}: {n.name}" for n in nodes)
    user_prompt = (
        f"Create {target} multiple-choice questions.\n\n"
        f"Visited spots (use these node ids for source_node_id):\n{node_index}\n\n"
        f"Heritage context:\n------------------\n{source_text}\n------------------"
    )

    try:
        reply = await call_openrouter([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        items = _coerce_json(reply)
        questions = _normalize(items, nodes)
    except Exception as exc:
        logger.warning(f"[quizgen] LLM generation failed, using fallback: {exc}")
        questions = []

    if len(questions) < MIN_QUESTIONS:
        # Top up / replace with templates so we always return a playable quiz.
        if not questions:
            questions = _fallback_questions(site, nodes)
        else:
            questions += _fallback_questions(site, nodes)

    return questions[:MAX_QUESTIONS]


async def generate_questions_for_node(
    db: Session,
    site: HeritageSite,
    node: Node,
    count: int = QUESTIONS_PER_NODE,
) -> List[dict]:
    """
    Generate up to [count] MCQs focused on a single visited node.
    Falls back to template questions if the LLM fails.
    """
    source_text = _build_source_text(db, site, [node])
    system_prompt = (
        "You are a quiz master for a heritage tourism app. Using ONLY the heritage "
        "context provided, write engaging multiple-choice questions about ONE specific "
        "spot the visitor just explored. Each question has exactly 4 options with exactly "
        "one correct answer. Keep questions concise and factual. Return STRICT JSON: an "
        "array of objects with keys \"question\" (string), \"options\" (array of 4 strings), "
        "\"correct_index\" (0-3 integer), and \"source_node_id\" (integer). "
        "Do not include any text outside the JSON array."
    )
    user_prompt = (
        f"Create {count} multiple-choice questions about this spot only.\n\n"
        f"node_id={node.id}: {node.name}\n\n"
        f"Heritage context:\n------------------\n{source_text}\n------------------"
    )
    questions: List[dict] = []
    try:
        reply = await call_openrouter([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        items = _coerce_json(reply)
        questions = _normalize(items, [node])
    except Exception as exc:
        logger.warning(f"[quizgen] per-node generation failed for node {node.id}: {exc}")

    if len(questions) < count:
        fb = _fallback_questions(site, [node])
        seen = {q["question"] for q in questions}
        for q in fb:
            if q["question"] not in seen:
                questions.append(q)
            if len(questions) >= count:
                break

    return questions[:count]
