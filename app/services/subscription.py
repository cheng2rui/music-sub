"""Subscription management service."""
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import Subscription

logger = logging.getLogger(__name__)


def get_all_subscriptions(enabled_only: bool = True) -> list[Subscription]:
    """Get all subscriptions."""
    db = SessionLocal()
    try:
        q = db.query(Subscription)
        if enabled_only:
            q = q.filter(Subscription.enabled == True)
        return q.all()
    finally:
        db.close()


def create_subscription(keyword: str, type: str = "artist",
                        quality: str = "any", sites: str = "all") -> Subscription:
    """Create a new subscription."""
    db = SessionLocal()
    try:
        sub = Subscription(keyword=keyword, type=type, quality=quality, sites=sites)
        db.add(sub)
        db.commit()
        db.refresh(sub)
        logger.info(f"Created subscription: {keyword} ({type})")
        return sub
    finally:
        db.close()


def delete_subscription(sub_id: int) -> bool:
    """Delete a subscription."""
    db = SessionLocal()
    try:
        sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
        if sub:
            db.delete(sub)
            db.commit()
            return True
        return False
    finally:
        db.close()


def update_last_search(sub_id: int):
    """Update last search timestamp."""
    db = SessionLocal()
    try:
        sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
        if sub:
            sub.last_search_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
