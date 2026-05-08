# app/main.py
# UPGRADED:
#   - Added /users and /community routers
#   - Removed install_review_triggers() — triggers replaced by transactional updates
#   - db_triggers.py is now dead code (safe to delete)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import sites, trips, chat, voice, admin, reviews, amenities
from app.routers import users, community

# Create all tables (new tables: users, node_ratings, node_comments,
# site_feedback, user_chat_history are created automatically here)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Dharohar Setu Backend",
    description="Heritage Travel Platform — SHREE AI Guide · IIIT Sonepat",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core
app.include_router(users.router)
app.include_router(sites.router)
app.include_router(trips.router)

# AI
app.include_router(chat.router)
app.include_router(voice.router)

# Reviews & ratings
app.include_router(reviews.router)

# Community (comments + feedback)
app.include_router(community.router)

# Discovery
app.include_router(amenities.router)

# Admin / seeding
app.include_router(admin.router)


@app.get("/")
def root():
    return {
        "service": "Dharohar Setu Backend",
        "version": "2.0.0",
        "assistant": "SHREE",
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "ok"}