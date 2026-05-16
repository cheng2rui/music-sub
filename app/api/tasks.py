"""Tasks API routes."""
import datetime
import os
import shutil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import DB_PATH, get_db
from app.models import DownloadTask, MusicFile
from app.schemas import DownloadTaskResponse
from app.services.pipeline import check_completed_downloads
from app.downloader.qbittorrent import qb_client

router = APIRouter()

VIDEO_LIKE_TERMS = (
    "mv", "mp4", "mkv", "concert", "live concert", "dvdrip", "4k", "2160p", "1080p",
    "h264", "h265", "x264", "x265", "ac3", "dvd", "subtitle", "video", "repair",
    "演唱会", "字幕", "修复", "视频",
)


def _is_qb_backed(task: DownloadTask) -> bool:
    return bool(task.torrent_hash) and not task.torrent_hash.startswith(("online:", "SIMULATED_"))


def _is_simulated(task: DownloadTask) -> bool:
    return bool(task.torrent_hash) and task.torrent_hash.startswith("SIMULATED_")


def _is_video_like(task: DownloadTask, qb_info: dict | None = None) -> bool:
    text = " ".join([
        task.torrent_name or "",
        (qb_info or {}).get("name") or "",
        (qb_info or {}).get("content_path") or "",
    ]).lower()
    return any(term in text for term in VIDEO_LIKE_TERMS)


def _task_to_response(task: DownloadTask, qb_info: dict | None = None) -> dict:
    """Convert ORM task to API response and enrich with qBittorrent state when available."""
    qb_info = qb_info or {}
    status = task.status
    qb_state = qb_info.get("qb_state")
    qb_missing = _is_qb_backed(task) and status in {"downloading", "paused", "organized"} and not qb_info

    if qb_missing:
        status = "missing"
    elif qb_state in {"stoppedDL", "stoppedUP", "pausedDL", "pausedUP"} and status in {"downloading", "paused"}:
        status = "paused"
    elif qb_state in {"error", "missingFiles", "unknown"}:
        status = "failed"
    elif qb_info.get("progress") == 1 and status == "downloading":
        status = "downloaded"
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
        "qb_missing": qb_missing,
        "download_speed": qb_info.get("download_speed"),
        "upload_speed": qb_info.get("upload_speed"),
        "eta": qb_info.get("eta"),
        "amount_left": qb_info.get("amount_left"),
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
        if _is_qb_backed(t)
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


def _build_cleanup_preview(db: Session) -> dict:
    """Find conservative cleanup candidates without changing anything."""
    tasks = db.query(DownloadTask).order_by(DownloadTask.created_at.asc()).all()
    qb_states = qb_client.get_torrents_by_hash([
        t.torrent_hash for t in tasks
        if _is_qb_backed(t)
    ])

    candidates = []
    keep = []
    unique_qb_hashes: set[str] = set()

    for task in tasks:
        qb_info = qb_states.get((task.torrent_hash or "").lower())
        effective = _task_to_response(task, qb_info)
        reasons = []
        cleanup_type = ""

        if _is_simulated(task):
            cleanup_type = "db_only"
            reasons.append("simulated_hash")
        elif _is_qb_backed(task):
            if effective["qb_missing"]:
                cleanup_type = "db_only"
                reasons.append("qb_missing")
            elif effective["status"] in {"failed", "missing"}:
                cleanup_type = "qb_and_db"
                reasons.append(f"status:{effective['status']}")
            elif effective["status"] == "paused" and (qb_info or {}).get("progress", 0) == 0 and _is_video_like(task, qb_info):
                cleanup_type = "qb_and_db"
                reasons.append("paused_zero_progress_video_like")
            elif task.status == "paused" and _is_video_like(task, qb_info):
                cleanup_type = "qb_and_db"
                reasons.append("paused_video_like")

        if cleanup_type:
            if _is_video_like(task, qb_info) and "video_like" not in reasons:
                reasons.append("video_like")
            if cleanup_type == "qb_and_db" and task.torrent_hash:
                unique_qb_hashes.add(task.torrent_hash.lower())
            candidates.append({
                "id": task.id,
                "torrent_name": task.torrent_name,
                "torrent_hash": task.torrent_hash,
                "site": task.site,
                "status": task.status,
                "effective_status": effective["status"],
                "size": task.size or 0,
                "qb_state": effective["qb_state"],
                "progress": effective["progress"],
                "amount_left": effective["amount_left"],
                "cleanup_type": cleanup_type,
                "reasons": reasons,
            })
        else:
            keep.append({
                "id": task.id,
                "torrent_name": task.torrent_name,
                "torrent_hash": task.torrent_hash,
                "site": task.site,
                "status": task.status,
                "effective_status": effective["status"],
            })

    return {
        "ok": True,
        "dry_run": True,
        "task_count": len(tasks),
        "candidate_count": len(candidates),
        "db_only_count": sum(1 for c in candidates if c["cleanup_type"] == "db_only"),
        "qb_and_db_count": sum(1 for c in candidates if c["cleanup_type"] == "qb_and_db"),
        "unique_qb_hash_count": len(unique_qb_hashes),
        "candidates": candidates,
        "keep": keep,
    }


@router.post("/cleanup/preview")
def preview_cleanup(db: Session = Depends(get_db)):
    """Dry-run dirty task cleanup and return candidates."""
    return _build_cleanup_preview(db)


@router.post("/cleanup/apply")
def apply_cleanup(delete_files: bool = False, db: Session = Depends(get_db)):
    """Apply conservative dirty task cleanup after preview.

    Files are preserved by default. Set delete_files=true to also ask qBittorrent to delete data.
    """
    preview = _build_cleanup_preview(db)
    candidates = preview["candidates"]
    task_ids = [c["id"] for c in candidates]
    qb_hashes = sorted({
        (c.get("torrent_hash") or "").lower()
        for c in candidates
        if c.get("cleanup_type") == "qb_and_db" and c.get("torrent_hash")
    })

    backup_path = None
    if task_ids and os.path.exists(DB_PATH):
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{DB_PATH}.bak.{timestamp}"
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        shutil.copy2(DB_PATH, backup_path)

    qb_deleted = []
    for torrent_hash in qb_hashes:
        qb_deleted.append({
            "hash": torrent_hash,
            "ok": qb_client.delete_torrent(torrent_hash, delete_files=delete_files),
        })

    music_files_deleted = 0
    tasks_deleted = 0
    if task_ids:
        music_files_deleted = db.query(MusicFile).filter(MusicFile.task_id.in_(task_ids)).delete(synchronize_session=False)
        tasks_deleted = db.query(DownloadTask).filter(DownloadTask.id.in_(task_ids)).delete(synchronize_session=False)
        db.commit()

    return {
        "ok": True,
        "dry_run": False,
        "delete_files": delete_files,
        "backup_path": backup_path,
        "tasks_deleted": tasks_deleted,
        "music_files_deleted": music_files_deleted,
        "qb_deleted": qb_deleted,
        "candidate_count": len(candidates),
    }


@router.post("/{task_id}/pause")
def pause_task(task_id: int, db: Session = Depends(get_db)):
    """Pause a qBittorrent-backed task and mark it paused in the DB."""
    task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if _is_qb_backed(task):
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
    if _is_qb_backed(task):
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
    if _is_qb_backed(task):
        qb_client.delete_torrent(task.torrent_hash, delete_files=delete_files)
    db.delete(task)
    db.commit()
    return {"ok": True}
