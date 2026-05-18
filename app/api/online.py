"""Online music direct download API."""
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import SessionLocal
from app.models import DownloadTask
from app.services.online_music import search_online, download_online_song
from app.services.pipeline import _process_completed_torrent

router = APIRouter()


class OnlineSearchRequest(BaseModel):
    keyword: str
    sources: list[str] = ["qq", "migu", "kugou", "netease", "kuwo"]
    limit: int = 20


class OnlineDownloadRequest(BaseModel):
    song: dict
    organize: bool = True


@router.post("/search")
def search(req: OnlineSearchRequest):
    """Search online music sources for direct downloadable songs."""
    keyword = req.keyword.strip()
    if not keyword:
        return []
    return search_online(keyword, req.sources, req.limit)


@router.post("/download")
def download(req: OnlineDownloadRequest):
    """Download one online song and optionally organize/scrape it immediately."""
    song = req.song or {}
    title = song.get("title") or song.get("filename") or "online-music"
    source = song.get("source") or "online"
    try:
        file_path = download_online_song(song)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {e}")

    synthetic_hash = f"online:{uuid.uuid4().hex}"
    db = SessionLocal()
    try:
        task = DownloadTask(
            torrent_name=title,
            torrent_hash=synthetic_hash,
            site=source,
            size=float(song.get("size") or 0),
            status="downloaded",
            save_path=file_path,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    finally:
        db.close()

    if req.organize:
        _process_completed_torrent({
            "hash": synthetic_hash,
            "name": title,
            "content_path": file_path,
            "metadata": {
                "source": source,
                "song_id": song.get("song_id") or "",
                "title": song.get("title") or title,
                "artist": song.get("artist") or "",
                "album": song.get("album") or "",
                "duration": song.get("duration") or 0,
            },
        })

    return {"ok": True, "file_path": file_path, "task_id": task_id, "organized": req.organize}
