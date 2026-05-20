"""Library file operation audit helpers."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import LibraryAuditEvent


def log_library_event(
    *,
    action: str,
    status: str = "ok",
    file_path: str | None = None,
    trash_path: str | None = None,
    restore_path: str | None = None,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    db: Session | None = None,
    commit: bool = False,
) -> None:
    """Record a best-effort library audit event.

    When a db session is provided the event joins the caller transaction unless
    commit=True. Without a db session this helper opens and commits its own short
    session. Audit failures must never block file operations.
    """
    own_db = db is None
    session = db or SessionLocal()
    try:
        event = LibraryAuditEvent(
            action=action,
            status=status,
            file_path=file_path,
            trash_path=trash_path,
            restore_path=restore_path,
            message=(message or "")[:500],
            details_json=json.dumps(details or {}, ensure_ascii=False),
        )
        session.add(event)
        if own_db or commit:
            session.commit()
    except Exception:
        try:
            if own_db or commit:
                session.rollback()
        except Exception:
            pass
    finally:
        if own_db:
            session.close()
