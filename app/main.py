from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import sites, trips, chat, voice, admin, reviews, amenities
from app.db_triggers import install_review_triggers

Base.metadata.create_all(bind=engine)
try:
    install_review_triggers()
except Exception:
    pass

app = FastAPI(
    title="HUMSAFAR Backend",
    description="Backend for Heritage Travel System with Shree AI Guide",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sites.router)
app.include_router(trips.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(admin.router)
app.include_router(reviews.router)
app.include_router(amenities.router)

@app.get("/")
def root():
    return {
        "message": "HUMSAFAR backend is running",
        "assistant": "Ritu"
    }