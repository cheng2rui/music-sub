"""Subscription API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Subscription
from app.schemas import SubscriptionCreate, SubscriptionResponse

router = APIRouter()


@router.get("/", response_model=list[SubscriptionResponse])
def list_subscriptions(db: Session = Depends(get_db)):
    """List all subscriptions."""
    return db.query(Subscription).order_by(Subscription.created_at.desc()).all()


@router.post("/", response_model=SubscriptionResponse)
def create_subscription(data: SubscriptionCreate, db: Session = Depends(get_db)):
    """Create a new subscription."""
    sub = Subscription(**data.model_dump())
    db.add(sub)
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
