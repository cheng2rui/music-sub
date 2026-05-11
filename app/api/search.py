"""Search API routes."""
from fastapi import APIRouter, HTTPException
from app.schemas import SearchRequest, TorrentResult
from app.services.searcher import search_sites, download_from_site
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
    """Download a specific torrent from a site."""
    torrent_hash = download_from_site(site, torrent_id)
    if not torrent_hash:
        raise HTTPException(status_code=500, detail="Failed to download torrent")

    # Record task
    db = SessionLocal()
    try:
        task = DownloadTask(
            torrent_name=title or torrent_id,
            torrent_hash=torrent_hash,
            site=site,
            status="downloading",
        )
        db.add(task)
        db.commit()
        return {"ok": True, "hash": torrent_hash, "task_id": task.id}
    finally:
        db.close()
