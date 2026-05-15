"""Library API routes."""
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, case
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


@router.get("/file/{file_id}")
def get_file_detail(file_id: int, db: Session = Depends(get_db)):
    """Get detailed info for a music file, including audio metadata."""
    f = db.query(MusicFile).filter(MusicFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")

    result = {
        "id": f.id,
        "file_path": f.file_path,
        "artist": f.artist,
        "album": f.album,
        "title": f.title,
        "year": f.year,
        "genre": f.genre,
        "format": f.format,
        "scraped": f.scraped,
        "has_cover": bool(_album_cover_path(f.file_path)),
        "bitrate": None,
        "sample_rate": None,
        "duration": None,
        "channels": None,
        "lyrics": None,
    }

    # Read audio metadata from actual file
    if f.file_path and os.path.exists(f.file_path):
        try:
            import mutagen
            audio = mutagen.File(f.file_path)
            if audio:
                info = audio.info
                result["bitrate"] = getattr(info, "bitrate", None)
                result["sample_rate"] = getattr(info, "sample_rate", None)
                result["duration"] = round(info.length, 1) if hasattr(info, "length") else None
                result["channels"] = getattr(info, "channels", None)
        except Exception:
            pass

        # Try to read lyrics from .lrc file
        lrc_path = Path(f.file_path).with_suffix(".lrc")
        if lrc_path.exists():
            try:
                result["lyrics"] = lrc_path.read_text(encoding="utf-8")[:5000]
            except Exception:
                pass

    return result


@router.post("/rescrape")
def rescrape_files(file_ids: list[int] = [], album_artist: str = "", album_name: str = "",
                  db: Session = Depends(get_db)):
    """Re-scrape metadata for specified files or an entire album."""
    from app.services.pipeline import _scrape_file
    from app.scrapers.tagger import tag_file, save_lyrics, save_cover

    # Get files to rescrape
    if file_ids:
        files = db.query(MusicFile).filter(MusicFile.id.in_(file_ids)).all()
    elif album_artist and album_name:
        files = (
            db.query(MusicFile)
            .filter(MusicFile.artist == album_artist)
            .filter(MusicFile.album == album_name)
            .all()
        )
    else:
        # Rescrape all unscraped
        files = db.query(MusicFile).filter(MusicFile.scraped == False).limit(50).all()

    if not files:
        return {"ok": True, "message": "没有需要刮削的文件", "scraped": 0, "total": 0}

    scraped_count = 0
    for f in files:
        if not f.file_path or not os.path.exists(f.file_path):
            continue
        meta = _scrape_file(f.file_path)
        if meta:
            tag_file(f.file_path, meta)
            if meta.lyrics:
                save_lyrics(f.file_path, meta.lyrics)
            if meta.cover_data:
                save_cover(str(Path(f.file_path).parent), meta.cover_data)
            f.artist = meta.artist
            f.album = meta.album
            f.title = meta.title
            f.year = meta.year
            f.genre = meta.genre
            f.scraped = True
            scraped_count += 1

    db.commit()
    return {"ok": True, "message": f"刮削完成 {scraped_count}/{len(files)}", "scraped": scraped_count, "total": len(files)}


@router.put("/file/{file_id}")
def update_file_tags(file_id: int, title: str = "", artist: str = "", album: str = "",
                    year: int = 0, genre: str = "", db: Session = Depends(get_db)):
    """Manually update tags for a music file (DB + audio file)."""
    f = db.query(MusicFile).filter(MusicFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")

    # Update DB record
    if title:
        f.title = title
    if artist:
        f.artist = artist
    if album:
        f.album = album
    if year:
        f.year = year
    if genre:
        f.genre = genre
    f.scraped = True
    db.commit()

    # Update actual audio file tags
    if f.file_path and os.path.exists(f.file_path):
        try:
            import music_tag
            audio = music_tag.load_file(f.file_path)
            if title:
                audio["title"] = title
            if artist:
                audio["artist"] = artist
            if album:
                audio["album"] = album
            if year:
                audio["year"] = year
            if genre:
                audio["genre"] = genre
            audio.save()
        except Exception as e:
            return {"ok": True, "message": f"DB已更新，但文件标签写入失败: {e}"}

    return {"ok": True, "message": "标签已更新"}

