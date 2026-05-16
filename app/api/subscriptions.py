"""Subscription API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Subscription
from app.schemas import SubscriptionCreate, SubscriptionUpdate, SubscriptionResponse

router = APIRouter()


@router.get("/", response_model=list[SubscriptionResponse])
def list_subscriptions(db: Session = Depends(get_db)):
    """List all subscriptions."""
    return db.query(Subscription).order_by(Subscription.created_at.desc()).all()


def _normalize_sites(value) -> str:
    if isinstance(value, list):
        cleaned = [str(v).strip() for v in value if str(v).strip()]
        return ",".join(cleaned) if cleaned else "all"
    return str(value or "all").strip() or "all"


@router.post("/", response_model=SubscriptionResponse)
def create_subscription(data: SubscriptionCreate, db: Session = Depends(get_db)):
    """Create a new subscription."""
    payload = data.model_dump()
    payload["keyword"] = payload.get("keyword", "").strip()
    payload["sites"] = _normalize_sites(payload.get("sites"))
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
    if "enabled" in payload and payload["enabled"] is not None:
        sub.enabled = bool(payload["enabled"])
    db.commit()
    db.refresh(sub)
    return sub


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
