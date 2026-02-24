from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Prompt
from app.schemas import ChatRequest, ChatResponse
from app.services.openrouter import call_openrouter

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, db: Session = Depends(get_db)):

    # 1️⃣ Fetch context from DB
    prompt_record = db.query(Prompt).filter(
        Prompt.site_id == req.site_id,
        Prompt.node_id == req.node_id
    ).first()

    if not prompt_record:
        # fallback to site-level prompt
        prompt_record = db.query(Prompt).filter(
            Prompt.site_id == req.site_id,
            Prompt.node_id == None
        ).first()

    if not prompt_record:
        raise HTTPException(status_code=404, detail="No heritage context available.")

    heritage_context = prompt_record.context_prompt_text

    # 2️⃣ Strict system prompt
    system_prompt = f"""
You are SHREE, the official AI heritage guide of HUMSAFAR.

You MUST follow these rules strictly:

1. Only answer using the heritage context provided below.
2. If the answer is not found in the context, say:
   "I can only answer based on available heritage information."
3. Do NOT invent facts.
4. Do NOT answer unrelated general knowledge questions.
5. Keep responses engaging but factual.

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