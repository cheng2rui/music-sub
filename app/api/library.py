"""Library API routes."""
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, Integer, case
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import MusicFile

router = APIRouter()


def _album_cover_path(file_path: str) -> str | None:
    """Find cover image alongside an audio file."""
    if not file_path:
        return None
    parent = Path(file_path).parent
    for name in ("cover.jpg", "cover.png", "folder.jpg", "front.jpg", "album.jpg"):
        p = parent / name
        if p.exists():
            return str(p)
    return None


@router.get("/")
def list_library(artist: str = "", album: str = "", limit: int = 50,
                 db: Session = Depends(get_db)):
    """Browse music library."""
    q = db.query(MusicFile).order_by(MusicFile.created_at.desc())
    if artist:
        q = q.filter(MusicFile.artist.ilike(f"%{artist}%"))
    if album:
        q = q.filter(MusicFile.album.ilike(f"%{album}%"))
    files = q.limit(limit).all()
    return [
        {
            "id": f.id,
            "file_path": f.file_path,
            "artist": f.artist,
            "album": f.album,
            "title": f.title,
            "year": f.year,
            "format": f.format,
            "scraped": f.scraped,
            "track_number": getattr(f, "track_number", None),
            "has_cover": bool(_album_cover_path(f.file_path)),
        }
        for f in files
    ]


@router.get("/albums")
def list_albums(artist: str = "", q: str = "", limit: int = 200,
                db: Session = Depends(get_db)):
    """List unique albums grouped by (artist, album), with track counts."""
    query = (
        db.query(
            MusicFile.artist.label("artist"),
            MusicFile.album.label("album"),
            func.min(MusicFile.year).label("year"),
            func.count(MusicFile.id).label("track_count"),
            func.sum(
                case((MusicFile.scraped == True, 1), else_=0)
            ).label("scraped_count"),
            func.min(MusicFile.file_path).label("sample_path"),
            func.max(MusicFile.created_at).label("updated_at"),
        )
        .filter(MusicFile.album.isnot(None))
        .filter(MusicFile.album != "")
        .group_by(MusicFile.artist, MusicFile.album)
    )
    if artist:
        query = query.filter(MusicFile.artist.ilike(f"%{artist}%"))
    if q:
        query = query.filter(
            (MusicFile.album.ilike(f"%{q}%")) | (MusicFile.artist.ilike(f"%{q}%"))
        )
    rows = query.order_by(func.max(MusicFile.created_at).desc()).limit(limit).all()
    result = []
    for r in rows:
        result.append({
            "artist": r.artist or "Unknown Artist",
            "album": r.album,
            "year": r.year,
            "track_count": int(r.track_count or 0),
            "scraped_count": int(r.scraped_count or 0),
            "has_cover": bool(_album_cover_path(r.sample_path)),
            "sample_id": None,
        })
    return result


@router.get("/album-tracks")
def list_album_tracks(artist: str, album: str, db: Session = Depends(get_db)):
    """List tracks in a specific album."""
    files = (
        db.query(MusicFile)
        .filter(MusicFile.artist == artist)
        .filter(MusicFile.album == album)
        .order_by(MusicFile.id.asc())
        .all()
    )
    return [
        {
            "id": f.id,
            "title": f.title or Path(f.file_path).stem,
            "artist": f.artist,
            "album": f.album,
            "year": f.year,
            "format": f.format,
            "scraped": f.scraped,
            "file_path": f.file_path,
        }
        for f in files
    ]


@router.get("/cover/{file_id}")
def get_cover(file_id: int, db: Session = Depends(get_db)):
    """Serve cover image for a music file's album folder."""
    f = db.query(MusicFile).filter(MusicFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    cover = _album_cover_path(f.file_path)
    if not cover:
        raise HTTPException(status_code=404, detail="No cover")
    return FileResponse(cover)


@router.get("/album-cover")
def get_album_cover(artist: str, album: str, db: Session = Depends(get_db)):
    """Serve cover for an album by (artist, album)."""
    f = (
        db.query(MusicFile)
        .filter(MusicFile.artist == artist)
        .filter(MusicFile.album == album)
        .first()
    )
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    cover = _album_cover_path(f.file_path)
    if not cover:
        raise HTTPException(status_code=404, detail="No cover")
    return FileResponse(cover)


@router.get("/stats")
def library_stats(db: Session = Depends(get_db)):
    """Get library statistics."""
    total = db.query(MusicFile).count()
    scraped = db.query(MusicFile).filter(MusicFile.scraped == True).count()
    artists = (
        db.query(MusicFile.artist)
        .filter(MusicFile.artist.isnot(None))
        .filter(MusicFile.artist != "")
        .distinct()
        .count()
    )
    albums = (
        db.query(MusicFile.artist, MusicFile.album)
        .filter(MusicFile.album.isnot(None))
        .filter(MusicFile.album != "")
        .distinct()
        .count()
    )
    return {
        "total_files": total,
        "scraped": scraped,
        "unscraped": total - scraped,
        "artists": artists,
        "albums": albums,
    }
