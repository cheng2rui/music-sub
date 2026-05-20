"""Subscription API routes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Subscription
from app.schemas import SubscriptionCreate, SubscriptionUpdate, SubscriptionResponse

router = APIRouter()


class SubscriptionBatchCreate(BaseModel):
    items: list[SubscriptionCreate]
    skip_duplicates: bool = True


class SubscriptionBatchDelete(BaseModel):
    ids: list[int] = []
    keyword_contains: str = ""
    type: str = ""
    enabled: bool | None = None
    delete_all: bool = False


@router.get("/", response_model=list[SubscriptionResponse])
def list_subscriptions(db: Session = Depends(get_db)):
    """List all subscriptions."""
    return db.query(Subscription).order_by(Subscription.created_at.desc()).all()


def _normalize_sites(value) -> str:
    if isinstance(value, list):
        cleaned = [str(v).strip() for v in value if str(v).strip()]
        return ",".join(cleaned) if cleaned else "all"
    return str(value or "all").strip() or "all"


def _normalize_source_preference(value) -> str:
    value = str(value or "pt").strip()
    return value if value in {"pt", "online_first", "online_only"} else "pt"


@router.post("/", response_model=SubscriptionResponse)
def create_subscription(data: SubscriptionCreate, db: Session = Depends(get_db)):
    """Create a new subscription."""
    payload = data.model_dump()
    payload["keyword"] = payload.get("keyword", "").strip()
    payload["sites"] = _normalize_sites(payload.get("sites"))
    payload["source_preference"] = _normalize_source_preference(payload.get("source_preference"))
    if not payload["keyword"]:
        raise HTTPException(status_code=400, detail="Keyword is required")
    sub = Subscription(**payload)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.put("/{sub_id}", response_model=SubscriptionResponse)
def update_subscription(sub_id: int, data: SubscriptionUpdate, db: Session = Depends(get_db)):
    """Update an existing subscription."""
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    payload = data.model_dump(exclude_unset=True)
    if "keyword" in payload:
        keyword = (payload.get("keyword") or "").strip()
        if not keyword:
            raise HTTPException(status_code=400, detail="Keyword is required")
        sub.keyword = keyword
    if "type" in payload and payload["type"] is not None:
        sub.type = payload["type"]
    if "quality" in payload and payload["quality"] is not None:
        sub.quality = payload["quality"]
    if "sites" in payload and payload["sites"] is not None:
        sub.sites = _normalize_sites(payload["sites"])
    if "source_preference" in payload and payload["source_preference"] is not None:
        sub.source_preference = _normalize_source_preference(payload["source_preference"])
    if "enabled" in payload and payload["enabled"] is not None:
        sub.enabled = bool(payload["enabled"])
    db.commit()
    db.refresh(sub)
    return sub


@router.post("/batch")
def create_subscriptions_batch(data: SubscriptionBatchCreate, db: Session = Depends(get_db)):
    """Create many subscriptions in one transaction."""
    items = data.items or []
    if len(items) > 5000:
        raise HTTPException(status_code=400, detail="一次最多批量添加 5000 个订阅")
    existing = set()
    if data.skip_duplicates:
        for row in db.query(Subscription.keyword, Subscription.type, Subscription.quality, Subscription.sites, Subscription.source_preference).all():
            existing.add((row.keyword.strip(), row.type, row.quality, row.sites or "all", row.source_preference or "pt"))
    added = 0
    skipped = 0
    for item in items:
        payload = item.model_dump()
        payload["keyword"] = payload.get("keyword", "").strip()
        payload["sites"] = _normalize_sites(payload.get("sites"))
        payload["source_preference"] = _normalize_source_preference(payload.get("source_preference"))
        if not payload["keyword"]:
            skipped += 1
            continue
        key = (
            payload["keyword"],
            payload.get("type") or "artist",
            payload.get("quality") or "any",
            payload["sites"],
            payload.get("source_preference") or "pt",
        )
        if data.skip_duplicates and key in existing:
            skipped += 1
            continue
        db.add(Subscription(**payload))
        existing.add(key)
        added += 1
    db.commit()
    return {"ok": True, "added": added, "skipped": skipped, "total": len(items)}


@router.delete("/batch")
def delete_subscriptions_batch(data: SubscriptionBatchDelete, db: Session = Depends(get_db)):
    """Delete selected subscriptions, or everything matching a filter."""
    q = db.query(Subscription)
    if data.ids:
        q = q.filter(Subscription.id.in_([int(x) for x in data.ids]))
    else:
        if not data.delete_all and not data.keyword_contains and not data.type and data.enabled is None:
            raise HTTPException(status_code=400, detail="请提供 ids、筛选条件或 delete_all=true")
        if data.keyword_contains:
            q = q.filter(Subscription.keyword.ilike(f"%{data.keyword_contains.strip()}%"))
        if data.type:
            q = q.filter(Subscription.type == data.type)
        if data.enabled is not None:
            q = q.filter(Subscription.enabled == bool(data.enabled))
    count = q.delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted": count}


@router.delete("/{sub_id}")
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    """Delete a subscription."""
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    db.delete(sub)
    db.commit()
    return {"ok": True}


@router.put("/{sub_id}/toggle")
def toggle_subscription(sub_id: int, db: Session = Depends(get_db)):
    """Toggle subscription enabled/disabled."""
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub.enabled = not sub.enabled
    db.commit()
    return {"ok": True, "enabled": sub.enabled}
