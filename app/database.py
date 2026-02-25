# app/database.py
# FIXED:
#   Added explicit check for DATABASE_URL so the app fails with a clear
#   error message instead of a cryptic TypeError when the env var is missing.

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Add it to your .env file, e.g.:\n"
        "  DATABASE_URL=postgresql://user:password@localhost:5432/humsafar"
    )

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()