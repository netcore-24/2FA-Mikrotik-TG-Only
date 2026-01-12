from __future__ import annotations

import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from mikrotik_2fa_bot.config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(database_url: str) -> None:
    # sqlite:///./data/app.db -> ensure ./data exists
    if not database_url.startswith("sqlite:///"):
        return
    path = database_url.removeprefix("sqlite:///")
    # Only handle local paths
    if path.startswith("/"):
        dir_path = os.path.dirname(path)
    else:
        dir_path = os.path.dirname(os.path.abspath(path))
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


_ensure_sqlite_dir(settings.DATABASE_URL)
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from mikrotik_2fa_bot import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

