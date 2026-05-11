"""Tasks API routes."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import DownloadTask
from app.schemas import DownloadTaskResponse
from app.services.pipeline import check_completed_downloads

router = APIRouter()


@router.get("/", response_model=list[DownloadTaskResponse])
def list_tasks(status: str = "", db: Session = Depends(get_db)):
    """List download tasks, optionally filtered by status."""
    q = db.query(DownloadTask).order_by(DownloadTask.created_at.desc())
    if status:
        q = q.filter(DownloadTask.status == status)
    return q.limit(100).all()


@router.post("/check")
def trigger_check():
    """Manually trigger download completion check."""
    check_completed_downloads()
    return {"ok": True, "message": "Check triggered"}
