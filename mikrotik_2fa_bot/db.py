from __future__ import annotations

import os
from contextlib import contextmanager
from sqlalchemy import create_engine, event
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

# Improve SQLite concurrency for bot + scheduler (avoid "database is locked")
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
        try:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA busy_timeout=5000;")
            cur.close()
        except Exception:
            pass
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from mikrotik_2fa_bot import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Lightweight SQLite migration (we don't ship Alembic).
    # Add new columns if they don't exist.
    if settings.DATABASE_URL.startswith("sqlite"):
        try:
            conn = engine.raw_connection()
            cur = conn.cursor()

            cur.execute("PRAGMA table_info(users);")
            cols = {row[1] for row in (cur.fetchall() or [])}  # row[1] == name
            if "require_confirmation" not in cols:
                cur.execute("ALTER TABLE users ADD COLUMN require_confirmation BOOLEAN;")
            if "firewall_rule_id" not in cols:
                cur.execute("ALTER TABLE users ADD COLUMN firewall_rule_id VARCHAR(255);")

            cur.execute("PRAGMA table_info(vpn_sessions);")
            cols = {row[1] for row in (cur.fetchall() or [])}
            if "confirm_last_sent_at" not in cols:
                cur.execute("ALTER TABLE vpn_sessions ADD COLUMN confirm_last_sent_at DATETIME;")
            if "confirm_sent_count" not in cols:
                cur.execute("ALTER TABLE vpn_sessions ADD COLUMN confirm_sent_count INTEGER DEFAULT 0;")

            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            # Best-effort: DB will still work, features will just be unavailable.
            pass


@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

