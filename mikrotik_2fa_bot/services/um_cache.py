from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from mikrotik_2fa_bot.models import UmUserCache
from mikrotik_2fa_bot.services import mikrotik_api


def refresh_um_users_cache(db: Session) -> int:
    """
    Refresh UM users cache in SQLite without holding a full list in memory.
    Returns number of usernames seen.

    Strategy:
      - stream usernames from router, upsert each with fetched_at=now
      - delete rows not seen in this refresh (fetched_at < now)
    """
    now = datetime.utcnow()
    seen = 0
    for uname in mikrotik_api.iter_user_manager_usernames():
        u = (uname or "").strip()
        if not u:
            continue
        seen += 1
        row = UmUserCache(username=u, fetched_at=now)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.query(UmUserCache).filter(UmUserCache.username == u).first()
            if existing:
                existing.fetched_at = now
                db.commit()
    # Remove entries that no longer exist on router
    db.query(UmUserCache).filter(UmUserCache.fetched_at < now).delete(synchronize_session=False)
    db.commit()
    return seen


def refresh_um_users_cache_in_new_session() -> int:
    """
    Convenience wrapper for running in a thread:
    opens its own DB session (SQLAlchemy sessions are not thread-safe).
    """
    from mikrotik_2fa_bot.db import db_session

    with db_session() as db:
        return refresh_um_users_cache(db)


def count_um_users_cache(db: Session) -> int:
    return int(db.query(UmUserCache).count())


def list_um_users_page(db: Session, page: int, page_size: int) -> list[UmUserCache]:
    page = max(0, int(page))
    size = max(1, int(page_size))
    return (
        db.query(UmUserCache)
        .order_by(UmUserCache.username.asc())
        .offset(page * size)
        .limit(size)
        .all()
    )

