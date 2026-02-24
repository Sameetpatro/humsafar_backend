# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import sites, trips, chat

# Create DB tables (only for development)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="HUMSAFAR Backend",
    description="Backend for Heritage Travel System with Ritu AI Guide",
    version="1.0.0"
)

# CORS (important for Android / frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(sites.router)
app.include_router(trips.router)
app.include_router(chat.router)


@app.get("/")
def root():
    return {
        "message": "HUMSAFAR backend is running",
        "assistant": "Ritu"
    }