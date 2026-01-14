from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mikrotik_2fa_bot.models import FirewallRuleCache
from mikrotik_2fa_bot.services import mikrotik_api


def _label_from_rule(r: dict) -> tuple[str, str] | None:
    rid = str(r.get(".id") or r.get("id") or "").strip()
    if not rid:
        return None
    chain = str(r.get("chain") or "-")
    action = str(r.get("action") or "-")
    disabled = str(r.get("disabled") or "false")
    comment = str((r.get("comment") or "")).strip()
    label = f"{rid} | {chain} | {action} | disabled={disabled} | {comment}"
    return rid, label[:512]


def refresh_firewall_rules_cache(comment_substring: str | None = None) -> int:
    """
    Refresh firewall rules cache (in the provided filter) without holding full rules list in memory.
    Returns number of rules seen (after filter).

    Strategy:
      - stream rules from router, upsert each with fetched_at=now
      - delete rows not seen in this refresh (fetched_at < now)
    """
    now = datetime.utcnow()
    seen = 0

    from mikrotik_2fa_bot.db import db_session

    with db_session() as db:
        for r in mikrotik_api.iter_firewall_filter_rules(comment_substring):
            item = _label_from_rule(r)
            if not item:
                continue
            rid, label = item
            seen += 1
            row = FirewallRuleCache(rule_id=rid, label=label, fetched_at=now)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.query(FirewallRuleCache).filter(FirewallRuleCache.rule_id == rid).first()
                if existing:
                    existing.label = label
                    existing.fetched_at = now
                    db.commit()

        db.query(FirewallRuleCache).filter(FirewallRuleCache.fetched_at < now).delete(synchronize_session=False)
        db.commit()

    return seen


def count_firewall_rules_cache(db: Session) -> int:
    return int(db.query(FirewallRuleCache).count())


def list_firewall_rules_page(db: Session, page: int, page_size: int) -> list[FirewallRuleCache]:
    page = max(0, int(page))
    size = max(1, int(page_size))
    return (
        db.query(FirewallRuleCache)
        .order_by(FirewallRuleCache.rule_id.asc())
        .offset(page * size)
        .limit(size)
        .all()
    )

