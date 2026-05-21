"""Helpers for recording subscription execution history."""
import datetime
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import SubscriptionRun


def _json_dumps(data: Any) -> str:
    if data is None:
        return ""
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"repr": repr(data)}, ensure_ascii=False)


def start_subscription_run(db: Session, sub) -> SubscriptionRun:
    """Create a running history row for one subscription search attempt."""
    run = SubscriptionRun(
        subscription_id=sub.id,
        keyword=sub.keyword,
        type=sub.type,
        source_preference=getattr(sub, "source_preference", None) or "pt",
        status="running",
        source="none",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_subscription_run(
    db: Session,
    run: SubscriptionRun | None,
    *,
    status: str,
    source: str = "",
    message: str = "",
    error: str = "",
    online_result_count: int | None = None,
    pt_result_count: int | None = None,
    selected_count: int | None = None,
    downloaded_count: int | None = None,
    fallback_used: bool | None = None,
    details: Any = None,
) -> None:
    """Finalize a subscription history row without failing the caller."""
    if not run:
        return
    try:
        run.status = status
        run.source = source or run.source or "none"
        run.message = (message or "")[:500]
        run.error = (error or "")[:2000] or None
        if online_result_count is not None:
            run.online_result_count = int(online_result_count or 0)
        if pt_result_count is not None:
            run.pt_result_count = int(pt_result_count or 0)
        if selected_count is not None:
            run.selected_count = int(selected_count or 0)
        if downloaded_count is not None:
            run.downloaded_count = int(downloaded_count or 0)
        if fallback_used is not None:
            run.fallback_used = bool(fallback_used)
        run.details_json = _json_dumps(details) if details is not None else run.details_json
        run.finished_at = datetime.datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
