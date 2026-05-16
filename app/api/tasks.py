"""Tasks API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import DownloadTask
from app.schemas import DownloadTaskResponse
from app.services.pipeline import check_completed_downloads
from app.downloader.qbittorrent import qb_client

router = APIRouter()


def _task_to_response(task: DownloadTask, qb_info: dict | None = None) -> dict:
    """Convert ORM task to API response and enrich with qBittorrent state when available."""
    qb_info = qb_info or {}
    status = task.status
    qb_state = qb_info.get("qb_state")
    if qb_state in {"stoppedDL", "stoppedUP", "pausedDL", "pausedUP"} and status in {"downloading", "paused"}:
        status = "paused"
    elif qb_state and status == "paused" and qb_state not in {"stoppedDL", "stoppedUP", "pausedDL", "pausedUP"}:
        status = "downloading"

    return {
        "id": task.id,
        "torrent_name": task.torrent_name,
        "torrent_hash": task.torrent_hash,
        "site": task.site,
        "status": status,
        "size": task.size or 0,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "qb_state": qb_state,
        "progress": qb_info.get("progress"),
    }


@router.get("/", response_model=list[DownloadTaskResponse])
def list_tasks(status: str = "", db: Session = Depends(get_db)):
    """List download tasks, optionally filtered by status, enriched with qBittorrent state."""
    q = db.query(DownloadTask).order_by(DownloadTask.created_at.desc())
    if status:
        q = q.filter(DownloadTask.status == status)
    tasks = q.limit(100).all()
    qb_states = qb_client.get_torrents_by_hash([
        t.torrent_hash for t in tasks
        if t.torrent_hash and not t.torrent_hash.startswith(("online:", "SIMULATED_"))
    ])
    return [
        _task_to_response(task, qb_states.get((task.torrent_hash or "").lower()))
        for task in tasks
    ]


@router.post("/check")
def trigger_check():
    """Manually trigger download completion check."""
    check_completed_downloads()
    return {"ok": True, "message": "Check triggered"}


@router.post("/{task_id}/pause")
def pause_task(task_id: int, db: Session = Depends(get_db)):
    """Pause a qBittorrent-backed task and mark it paused in the DB."""
    task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.torrent_hash and not task.torrent_hash.startswith(("online:", "SIMULATED_")):
        if not qb_client.pause_torrent(task.torrent_hash):
            raise HTTPException(status_code=500, detail="Failed to pause torrent")
    task.status = "paused"
    db.commit()
    return {"ok": True}


@router.post("/{task_id}/resume")
def resume_task(task_id: int, db: Session = Depends(get_db)):
    """Resume a qBittorrent-backed task and mark it downloading in the DB."""
    task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.torrent_hash and not task.torrent_hash.startswith(("online:", "SIMULATED_")):
        if not qb_client.resume_torrent(task.torrent_hash):
            raise HTTPException(status_code=500, detail="Failed to resume torrent")
    task.status = "downloading"
    db.commit()
    return {"ok": True}


@router.delete("/{task_id}")
def delete_task(task_id: int, delete_files: bool = False, db: Session = Depends(get_db)):
    """Delete a task record and remove its qBittorrent task when present.

    Files are preserved by default. Pass delete_files=true to ask qBittorrent to delete data too.
    """
    task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.torrent_hash and not task.torrent_hash.startswith(("online:", "SIMULATED_")):
        qb_client.delete_torrent(task.torrent_hash, delete_files=delete_files)
    db.delete(task)
    db.commit()
    return {"ok": True}
