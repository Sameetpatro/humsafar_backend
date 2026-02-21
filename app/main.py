# app/main.py  ← REPLACE EXISTING FILE
# CHANGES vs previous:
#   + video router registered
#   + /static/videos served via StaticFiles

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.models       import ChatRequest, ChatResponse
from app.services     import call_openrouter
from app.routers      import voice as voice_router
from app.routers      import video as video_router

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt = "%H:%M:%S",
)

app = FastAPI(title="Humsafar API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ── Static video files ────────────────────────────────────────────────────────
_static_video_dir = Path("static/videos")
_static_video_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/videos", StaticFiles(directory=str(_static_video_dir)), name="videos")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(voice_router.router)
app.include_router(video_router.router)


# ── Existing /chat endpoint (unchanged) ──────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    system_prompt = f"""
    You are HUMSAFAR, an intelligent heritage guide.
    User is currently at: {req.site_name}
    Instructions:
    - If question is about the monument, answer in detail.
    - Suggest important areas to explore.
    - If question is general, answer normally.
    - Keep responses engaging and clear.
    - Do not hallucinate unknown facts.
    """
    messages  = [{"role": "system", "content": system_prompt}]
    messages += req.history
    messages.append({"role": "user", "content": req.message})
    reply = await call_openrouter(messages)
    return ChatResponse(reply=reply)