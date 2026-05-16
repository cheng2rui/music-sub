"""Search API routes."""
from fastapi import APIRouter, HTTPException
from app.schemas import SearchRequest, TorrentResult
from app.services.searcher import search_sites, fetch_torrent_info_hash, download_torrent_content
from app.services.notify import notify_download_added
from app.downloader.qbittorrent import qb_client
from app.db import SessionLocal
from app.models import DownloadTask

router = APIRouter()


@router.post("/", response_model=list[TorrentResult])
def search_torrents(req: SearchRequest):
    """Search PT sites for music torrents."""
    results = search_sites(req.keyword, req.sites or None)
    return [
        TorrentResult(
            site=r.site,
            title=r.title,
            torrent_id=r.torrent_id,
            size=r.size,
            seeders=r.seeders,
            leechers=r.leechers,
            upload_time=r.upload_time,
            free=r.free,
        )
        for r in results
    ]


@router.post("/download")
def download_torrent(site: str, torrent_id: str, title: str = ""):
    """Download a specific torrent from a site with DB/qB deduplication."""
    expected_hash, torrent_content = fetch_torrent_info_hash(site, torrent_id)
    if not expected_hash or not torrent_content:
        raise HTTPException(status_code=500, detail="Failed to download torrent")

    db = SessionLocal()
    try:
        existing = db.query(DownloadTask).filter(DownloadTask.torrent_hash == expected_hash).first()
        if existing:
            return {
                "ok": True,
                "hash": expected_hash,
                "task_id": existing.id,
                "already_exists": True,
                "message": "Already tracked",
            }

        qb_info = {}
        try:
            qb_info = qb_client.get_torrents_by_hash([expected_hash]).get(expected_hash) or {}
        except Exception:
            qb_info = {}

        torrent_hash = expected_hash if qb_info else download_torrent_content(torrent_content)
        if not torrent_hash:
            raise HTTPException(status_code=500, detail="Failed to add torrent")

        task = DownloadTask(
            torrent_name=title or qb_info.get("name") or torrent_id,
            torrent_hash=torrent_hash.lower(),
            site=site,
            size=float(qb_info.get("size") or 0),
            status="paused" if qb_info.get("qb_state") in {"stoppedDL", "stoppedUP", "pausedDL", "pausedUP"} else "downloading",
            save_path=qb_info.get("content_path") or qb_info.get("save_path"),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        if qb_info:
            return {
                "ok": True,
                "hash": torrent_hash.lower(),
                "task_id": task.id,
                "already_exists": True,
                "message": "Imported existing qB task",
            }
        notify_download_added(task.torrent_name, site)
        return {"ok": True, "hash": torrent_hash.lower(), "task_id": task.id, "already_exists": False}
    finally:
        db.close()
