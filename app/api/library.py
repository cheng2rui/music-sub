"""Library API routes."""
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from app.auth import verify_token
from app.db import get_db
from app.models import MusicFile

router = APIRouter()

UNKNOWN_ALBUM = "单曲/未知专辑"


def _display_album(album: str | None) -> str:
    """Return a stable display album for singles or missing album metadata."""
    return album or UNKNOWN_ALBUM


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
        if album == UNKNOWN_ALBUM:
            q = q.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
        else:
            q = q.filter(MusicFile.album.ilike(f"%{album}%"))
    files = q.limit(limit).all()
    return [
        {
            "id": f.id,
            "file_path": f.file_path,
            "artist": f.artist,
            "album": _display_album(f.album),
            "title": f.title,
            "year": f.year,
            "format": f.format,
            "scraped": f.scraped,
            "track_number": f.track_number,
            "disc_number": f.disc_number,
            "duration": f.duration,
            "bitrate": f.bitrate,
            "sample_rate": f.sample_rate,
            "channels": f.channels,
            "has_cover": bool(_album_cover_path(f.file_path)),
        }
        for f in files
    ]


@router.get("/albums")
def list_albums(artist: str = "", q: str = "", limit: int = 200, offset: int = 0,
                db: Session = Depends(get_db)):
    """List unique albums grouped by (artist, album), with track counts."""
    album_group = func.coalesce(func.nullif(MusicFile.album, ""), UNKNOWN_ALBUM)
    query = (
        db.query(
            MusicFile.artist.label("artist"),
            album_group.label("album"),
            func.min(MusicFile.year).label("year"),
            func.count(MusicFile.id).label("track_count"),
            func.sum(
                case((MusicFile.scraped == True, 1), else_=0)
            ).label("scraped_count"),
            func.min(MusicFile.file_path).label("sample_path"),
            func.max(MusicFile.created_at).label("updated_at"),
        )
        .group_by(MusicFile.artist, album_group)
    )
    if artist:
        query = query.filter(MusicFile.artist.ilike(f"%{artist}%"))
    if q:
        query = query.filter(
            (MusicFile.album.ilike(f"%{q}%")) | (MusicFile.artist.ilike(f"%{q}%"))
        )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    rows = query.order_by(func.max(MusicFile.created_at).desc()).offset(offset).limit(limit).all()
    result = []
    for r in rows:
        result.append({
            "artist": r.artist or "Unknown Artist",
            "album": _display_album(r.album),
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
    query = db.query(MusicFile).filter(MusicFile.artist == artist)
    if album == UNKNOWN_ALBUM:
        query = query.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
    else:
        query = query.filter(MusicFile.album == album)
    files = query.order_by(
        MusicFile.disc_number.is_(None),
        MusicFile.disc_number.asc(),
        MusicFile.track_number.is_(None),
        MusicFile.track_number.asc(),
        MusicFile.id.asc(),
    ).all()
    return [
        {
            "id": f.id,
            "title": f.title or Path(f.file_path).stem,
            "artist": f.artist,
            "album": _display_album(f.album),
            "year": f.year,
            "track_number": f.track_number,
            "disc_number": f.disc_number,
            "duration": f.duration,
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
    query = db.query(MusicFile).filter(MusicFile.artist == artist)
    if album == UNKNOWN_ALBUM:
        query = query.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
    else:
        query = query.filter(MusicFile.album == album)
    f = query.first()
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
    album_group = func.coalesce(func.nullif(MusicFile.album, ""), UNKNOWN_ALBUM)
    albums = (
        db.query(MusicFile.artist, album_group)
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


@router.get("/stream/{file_id}")
def stream_file(file_id: int, token: str = Query(""), db: Session = Depends(get_db)):
    """Stream an audio file for in-browser playback.

    The endpoint accepts a JWT token query parameter because native audio elements
    cannot attach Authorization headers.
    """
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="登录已过期")
    f = db.query(MusicFile).filter(MusicFile.id == file_id).first()
    if not f or not f.file_path or not os.path.exists(f.file_path):
        raise HTTPException(status_code=404, detail="Not found")
    media_type = {
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "m4a": "audio/mp4",
        "aac": "audio/aac",
        "ogg": "audio/ogg",
        "ape": "audio/ape",
    }.get((f.format or Path(f.file_path).suffix.lstrip(".")).lower(), "application/octet-stream")
    return FileResponse(f.file_path, media_type=media_type, filename=Path(f.file_path).name)


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
        "album": _display_album(f.album),
        "title": f.title,
        "year": f.year,
        "genre": f.genre,
        "format": f.format,
        "scraped": f.scraped,
        "has_cover": bool(_album_cover_path(f.file_path)),
        "track_number": f.track_number,
        "disc_number": f.disc_number,
        "bitrate": f.bitrate,
        "sample_rate": f.sample_rate,
        "duration": f.duration,
        "channels": f.channels,
        "lyrics": None,
    }

    # Fall back to reading audio metadata from disk for older DB rows.
    if f.file_path and os.path.exists(f.file_path):
        if not all(result.get(k) for k in ("duration", "bitrate", "sample_rate", "channels")):
            try:
                from app.scrapers.tagger import read_audio_metadata
                audio_meta = read_audio_metadata(f.file_path)
                for key, value in audio_meta.items():
                    if result.get(key) is None and value is not None:
                        result[key] = value
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
    from app.scrapers.tagger import tag_file, save_lyrics, save_cover, read_audio_metadata

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
            f.track_number = meta.track_number or None
            f.disc_number = meta.disc_number or None
            audio_meta = read_audio_metadata(f.file_path)
            f.duration = audio_meta.get("duration")
            f.bitrate = audio_meta.get("bitrate")
            f.sample_rate = audio_meta.get("sample_rate")
            f.channels = audio_meta.get("channels")
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

