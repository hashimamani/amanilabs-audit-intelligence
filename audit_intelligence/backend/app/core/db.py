"""
DATABASE_URL env var selects the backend: unset defaults to SQLite for
zero-infra local dev, set (e.g. by docker-compose to a postgresql+psycopg://
URL) switches to Postgres. SQLAlchemy is the abstraction boundary that
makes this a config change, not an app rewrite - see db/models.py, which
deliberately avoids any SQLite- or Postgres-specific column types.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

BACKEND_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BACKEND_DIR / "audit_intelligence.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DB_PATH}"

DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
