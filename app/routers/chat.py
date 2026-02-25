# app/routers/chat.py
# FIXED:
#   3-tier fallback so chatbot never returns 404:
#     1. Node-specific Prompt row    (richest context)
#     2. Site-level Prompt row       (good context)
#     3. HeritageSite table fields   (always available — summary, history, fun_facts)
#   This means chat works immediately after seed-bulk, even before seed-prompt.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Prompt, HeritageSite, Node
from app.schemas import ChatRequest, ChatResponse
from app.services.openrouter import call_openrouter   # direct import, no circular risk

router = APIRouter(prefix="/chat", tags=["Chat"])


def _build_fallback_context(site: HeritageSite, node: Node | None) -> str:
    parts = [f"Heritage Site: {site.name}"]
    if site.summary:
        parts.append(f"Summary: {site.summary}")
    if site.history:
        parts.append(f"History: {site.history}")
    if site.fun_facts:
        parts.append(f"Fun Facts: {site.fun_facts}")
    if site.helpline_number:
        parts.append(f"Helpline: {site.helpline_number}")
    if node:
        parts.append(f"\nCurrently at: {node.name} (stop #{node.sequence_order})")
        if node.description:
            parts.append(f"About this spot: {node.description}")
    if len(parts) == 1:
        parts.append(
            f"{site.name} is a heritage site at "
            f"({site.latitude:.4f}, {site.longitude:.4f}). "
            "Please add summary/history via the admin seed-bulk endpoint for richer responses."
        )
    return "\n".join(parts)


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, db: Session = Depends(get_db)):

    # Tier 1 — node-specific prompt
    prompt_record = None
    if req.node_id:
        prompt_record = db.query(Prompt).filter(
            Prompt.site_id == req.site_id,
            Prompt.node_id == req.node_id,
        ).first()

    # Tier 2 — site-level prompt
    if not prompt_record:
        prompt_record = db.query(Prompt).filter(
            Prompt.site_id == req.site_id,
            Prompt.node_id == None,
        ).first()

    # Tier 3 — build from HeritageSite + Node columns
    if prompt_record:
        heritage_context = prompt_record.context_prompt_text
    else:
        site = db.query(HeritageSite).filter(HeritageSite.id == req.site_id).first()
        if not site:
            raise HTTPException(
                status_code=404,
                detail=f"Site {req.site_id} not found. Seed it via POST /admin/seed-bulk first."
            )
        node = db.query(Node).filter(Node.id == req.node_id).first() if req.node_id else None
        heritage_context = _build_fallback_context(site, node)

    system_prompt = f"""You are SHREE, the official AI heritage guide of HUMSAFAR.

Rules:
1. Answer using the heritage context provided below.
2. If the answer is not in the context, use your general knowledge about this site.
3. Never invent false facts.
4. Be engaging, warm, and concise (3-5 sentences unless asked for more).
5. Do not use markdown formatting - responses are displayed in a mobile app.

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