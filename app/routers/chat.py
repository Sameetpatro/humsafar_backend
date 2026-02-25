# app/routers/chat.py
# 2-LEVEL PROMPTING:
#   Level 1 — User enters geofence, no QR scanned yet:
#             node_id = null → loads site-wide prompt → general campus context
#   Level 2 — User scans a QR code at a specific node:
#             node_id = X   → loads node-specific prompt → Mann Sir Cave etc.
#
# Fallback chain (if no prompt seeded):
#   Node prompt → Site prompt → HeritageSite DB columns → bare minimum

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Prompt, HeritageSite, Node
from app.schemas import ChatRequest, ChatResponse
from app.services.openrouter import call_openrouter

router = APIRouter(prefix="/chat", tags=["Chat"])


def _build_fallback_context(site: HeritageSite, node: Node | None) -> str:
    parts = [f"Site: {site.name}"]
    if site.summary:
        parts.append(f"Summary: {site.summary}")
    if site.history:
        parts.append(f"History: {site.history}")
    if site.fun_facts:
        parts.append(f"Fun Facts: {site.fun_facts}")
    if site.helpline_number:
        parts.append(f"Helpline: {site.helpline_number}")
    if node:
        parts.append(f"\nCurrently at: {node.name}")
        if node.description:
            parts.append(f"About this spot: {node.description}")
    return "\n".join(parts)


def _get_context_and_level(
    db: Session,
    site_id: int,
    node_id: int | None
) -> tuple[str, str]:
    """
    Returns (heritage_context, level_label).
    Level 1 = site-wide (no QR scanned yet)
    Level 2 = node-specific (QR scanned)
    """

    # Level 2 — node-specific prompt
    if node_id:
        node_prompt = db.query(Prompt).filter(
            Prompt.site_id == site_id,
            Prompt.node_id == node_id,
        ).first()
        if node_prompt:
            node = db.query(Node).filter(Node.id == node_id).first()
            node_name = node.name if node else f"Node {node_id}"
            return node_prompt.context_prompt_text, f"node:{node_name}"

    # Level 1 — site-wide prompt
    site_prompt = db.query(Prompt).filter(
        Prompt.site_id == site_id,
        Prompt.node_id == None,
    ).first()
    if site_prompt:
        return site_prompt.context_prompt_text, "site:general"

    # Fallback — build from HeritageSite DB columns
    site = db.query(HeritageSite).filter(HeritageSite.id == site_id).first()
    if not site:
        raise HTTPException(
            status_code=404,
            detail=f"Site {site_id} not found. Seed it via POST /admin/seed-bulk first."
        )
    node = db.query(Node).filter(Node.id == node_id).first() if node_id else None
    context = _build_fallback_context(site, node)
    level = f"node:{node.name}" if node else "site:general"
    return context, level


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, db: Session = Depends(get_db)):

    heritage_context, level = _get_context_and_level(db, req.site_id, req.node_id)

    if level.startswith("node:"):
        node_name = level.split("node:")[1]
        guide_intro = (
            f"You are SHREE, the AI guide of HUMSAFAR. "
            f"The visitor has scanned the QR and is standing at: {node_name}. "
            f"Answer questions specifically about this location using the context below."
        )
    else:
        guide_intro = (
            "You are SHREE, the AI guide of HUMSAFAR. "
            "The visitor has just entered this site. "
            "Answer general questions about this place using the context below."
        )

    system_prompt = f"""{guide_intro}

Rules:
1. Answer using the heritage context provided below.
2. If the answer is not in the context, use your general knowledge about this specific site.
3. Never invent false facts. Never say any historical king or Mughal emperor built this place.
4. Be engaging, warm, and conversational — like a knowledgeable local guide.
5. Keep responses to 3-5 sentences unless asked for more detail.
6. Do not use markdown, asterisks, or bullet points — plain text only.
7. Address the visitor directly and make them feel welcome.

Heritage Context:
------------------
{heritage_context}
------------------
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in req.history]
    messages.append({"role": "user", "content": req.message})

    reply = await call_openrouter(messages)
    return ChatResponse(reply=reply)