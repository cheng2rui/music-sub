"""Library API routes."""
import os
import subprocess
from pathlib import Path
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from app.auth import verify_token
from app.config import config
from app.db import get_db
from app.models import MusicFile

router = APIRouter()

UNKNOWN_ALBUM = "单曲/未知专辑"
UNKNOWN_ARTIST = "Unknown Artist"


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
def list_library(artist: str = "", album: str = "", q: str = "", limit: int = 50,
                 db: Session = Depends(get_db)):
    """Browse music library."""
    query = db.query(MusicFile).order_by(MusicFile.created_at.desc())
    if artist:
        query = query.filter(MusicFile.artist.ilike(f"%{artist}%"))
    if album:
        if album == UNKNOWN_ALBUM:
            query = query.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
        else:
            query = query.filter(MusicFile.album.ilike(f"%{album}%"))
    if q:
        like = f"%{q}%"
        query = query.filter(
            (MusicFile.title.ilike(like)) |
            (MusicFile.artist.ilike(like)) |
            (MusicFile.album.ilike(like)) |
            (MusicFile.file_path.ilike(like))
        )
    limit = max(1, min(limit, 500))
    files = query.limit(limit).all()
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
def list_albums(artist: str = "", q: str = "", sort: str = "updated", limit: int = 200, offset: int = 0,
                db: Session = Depends(get_db)):
    """List unique albums grouped by (artist, album), with library-friendly stats."""
    album_group = func.coalesce(func.nullif(MusicFile.album, ""), UNKNOWN_ALBUM)
    latest_at = func.max(MusicFile.created_at)
    track_count = func.count(MusicFile.id)
    query = (
        db.query(
            MusicFile.artist.label("artist"),
            album_group.label("album"),
            func.min(MusicFile.year).label("year"),
            track_count.label("track_count"),
            func.sum(case((MusicFile.scraped == True, 1), else_=0)).label("scraped_count"),
            func.sum(func.coalesce(MusicFile.duration, 0)).label("total_duration"),
            func.avg(MusicFile.bitrate).label("avg_bitrate"),
            func.group_concat(func.distinct(func.upper(MusicFile.format))).label("formats"),
            func.min(MusicFile.id).label("sample_id"),
            func.min(MusicFile.file_path).label("sample_path"),
            latest_at.label("updated_at"),
        )
        .group_by(MusicFile.artist, album_group)
    )
    if artist:
        query = query.filter(MusicFile.artist.ilike(f"%{artist}%"))
    if q:
        query = query.filter(
            (MusicFile.album.ilike(f"%{q}%")) |
            (MusicFile.artist.ilike(f"%{q}%")) |
            (MusicFile.title.ilike(f"%{q}%"))
        )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    sort_map = {
        "updated": latest_at.desc(),
        "name": album_group.asc(),
        "artist": MusicFile.artist.asc(),
        "tracks": track_count.desc(),
        "year": func.min(MusicFile.year).desc(),
    }
    rows = query.order_by(sort_map.get(sort, latest_at.desc())).offset(offset).limit(limit).all()
    result = []
    for r in rows:
        result.append({
            "artist": r.artist or UNKNOWN_ARTIST,
            "album": _display_album(r.album),
            "year": r.year,
            "track_count": int(r.track_count or 0),
            "scraped_count": int(r.scraped_count or 0),
            "total_duration": float(r.total_duration or 0),
            "avg_bitrate": int(r.avg_bitrate or 0) if r.avg_bitrate else None,
            "formats": [x for x in (r.formats or "").split(",") if x],
            "has_cover": bool(_album_cover_path(r.sample_path)),
            "sample_id": r.sample_id,
        })
    return result


@router.get("/album-tracks")
def list_album_tracks(artist: str, album: str, db: Session = Depends(get_db)):
    """List tracks in a specific album."""
    query = db.query(MusicFile)
    if artist == UNKNOWN_ARTIST:
        query = query.filter((MusicFile.artist.is_(None)) | (MusicFile.artist == ""))
    else:
        query = query.filter(MusicFile.artist == artist)
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
    query = db.query(MusicFile)
    if artist == UNKNOWN_ARTIST:
        query = query.filter((MusicFile.artist.is_(None)) | (MusicFile.artist == ""))
    else:
        query = query.filter(MusicFile.artist == artist)
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


def _has_lrc(file_path: str | None) -> bool:
    if not file_path:
        return False
    try:
        return Path(file_path).with_suffix(".lrc").exists()
    except Exception:
        return False


def _is_unknown_artist(artist: str | None) -> bool:
    if not artist:
        return True
    a = artist.strip().lower()
    return a in {"", "unknown artist", "未知艺人", "unknown", "various artists"}


_HEALTH_KINDS = ("missing_cover", "missing_lyrics", "missing_duration", "unknown_artist", "unscraped", "cue_candidates")


@router.get("/health")
def library_health(kind: str = "", limit: int = 100, db: Session = Depends(get_db)):
    """Report library hygiene issues grouped by album."""
    files = db.query(MusicFile).all()
    limit = max(1, min(limit, 1000))
    buckets: dict[str, dict[tuple[str, str], dict]] = {k: {} for k in _HEALTH_KINDS}
    totals = {k: 0 for k in _HEALTH_KINDS}

    def _has_cue(f: MusicFile) -> bool:
        if not f.file_path:
            return False
        p = Path(f.file_path)
        if p.with_suffix(".cue").exists():
            return True
        try:
            return len(list(p.parent.glob("*.cue"))) == 1
        except Exception:
            return False

    def _add(bucket_key: str, f: MusicFile):
        artist = (f.artist or "").strip() or UNKNOWN_ARTIST
        album = _display_album(f.album)
        key = (artist, album)
        bucket = buckets[bucket_key]
        if key not in bucket:
            bucket[key] = {
                "artist": artist,
                "album": album,
                "track_count": 0,
                "sample_track_id": f.id,
                "sample_path": f.file_path,
                "has_cover": bool(_album_cover_path(f.file_path)),
            }
        bucket[key]["track_count"] += 1
        totals[bucket_key] += 1

    for f in files:
        if not _album_cover_path(f.file_path):
            _add("missing_cover", f)
        if not _has_lrc(f.file_path):
            _add("missing_lyrics", f)
        if not f.duration or f.duration <= 0:
            _add("missing_duration", f)
        if _is_unknown_artist(f.artist):
            _add("unknown_artist", f)
        if not f.scraped:
            _add("unscraped", f)
        if _has_cue(f):
            _add("cue_candidates", f)

    def _serialize(bucket_key: str):
        items = list(buckets[bucket_key].values())
        items.sort(key=lambda x: x["track_count"], reverse=True)
        return items[:limit]

    if kind:
        if kind not in _HEALTH_KINDS:
            raise HTTPException(status_code=400, detail="未知治理类别")
        return {
            "kind": kind,
            "total": totals[kind],
            "items": _serialize(kind),
        }

    return {
        "totals": totals,
        "samples": {k: _serialize(k)[:5] for k in _HEALTH_KINDS},
    }


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


def _probe_audio_codec(file_path: Path) -> str:
    """Return audio codec name via ffprobe, or empty string if unavailable."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1",
                str(file_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
        return (result.stdout or "").strip().splitlines()[0].lower()
    except Exception:
        return ""


@router.get("/stream/{file_id}")
def stream_file(request: Request, file_id: int, token: str = Query(""), db: Session = Depends(get_db)):
    """Stream an audio file with HTTP Range support for seekable playback.

    HTML audio elements rely on `Range: bytes=...` for seeking, and Safari/Chrome
    are especially strict for MP4/M4A containers. FastAPI's FileResponse may send
    the full file with 200 in this stack, so implement byte ranges explicitly.
    """
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="登录已过期")
    f = db.query(MusicFile).filter(MusicFile.id == file_id).first()
    if not f or not f.file_path or not os.path.exists(f.file_path):
        raise HTTPException(status_code=404, detail="Not found")

    file_path = Path(f.file_path)
    ext = (f.format or file_path.suffix.lstrip(".")).lower()
    # ALAC inside .m4a is not supported by Chrome/Edge/Firefox. Safari may play it,
    # but a universal player should fall back to MP3 transcoding.
    if ext in {"m4a", "mp4"} and _probe_audio_codec(file_path) == "alac":
        return stream_transcoded_audio(file_id=file_id, token=token, db=db)

    file_size = file_path.stat().st_size
    media_type = {
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "m4a": "audio/mp4",
        "mp4": "audio/mp4",
        "aac": "audio/aac",
        "ogg": "audio/ogg",
        "ape": "audio/ape",
    }.get(ext, "application/octet-stream")

    def iter_file(start: int, end: int, chunk_size: int = 1024 * 1024):
        with open(file_path, "rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    range_header = request.headers.get("range")
    from urllib.parse import quote
    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(file_path.name)}",
    }
    if range_header:
        import re
        m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not m:
            raise HTTPException(status_code=416, detail="Invalid range")
        start_s, end_s = m.groups()
        if start_s:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
        else:
            # suffix range: bytes=-500 means last 500 bytes
            suffix = int(end_s or 0)
            start = max(file_size - suffix, 0)
            end = file_size - 1
        if start >= file_size or end < start:
            return StreamingResponse(
                iter(()),
                status_code=416,
                headers={**common_headers, "Content-Range": f"bytes */{file_size}"},
                media_type=media_type,
            )
        end = min(end, file_size - 1)
        length = end - start + 1
        return StreamingResponse(
            iter_file(start, end),
            status_code=206,
            media_type=media_type,
            headers={
                **common_headers,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
            },
        )

    return StreamingResponse(
        iter_file(0, file_size - 1),
        media_type=media_type,
        headers={**common_headers, "Content-Length": str(file_size)},
    )


@router.get("/stream-transcoded/{file_id}")
def stream_transcoded_audio(file_id: int, token: str = Query(""), db: Session = Depends(get_db)):
    """Transcode browser-unfriendly audio (notably ALAC-in-M4A) to MP3 on the fly.

    Chrome/Edge/Firefox generally cannot decode ALAC even when the container is
    .m4a. Safari can, but behavior varies. This endpoint gives the player a
    universal MP3 fallback without mutating the library file.
    """
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="登录已过期")
    f = db.query(MusicFile).filter(MusicFile.id == file_id).first()
    if not f or not f.file_path or not os.path.exists(f.file_path):
        raise HTTPException(status_code=404, detail="Not found")

    file_path = Path(f.file_path)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(file_path),
        "-vn", "-map", "0:a:0", "-codec:a", "libmp3lame", "-b:a", "320k",
        "-f", "mp3", "pipe:1",
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ffmpeg not installed")

    def iter_transcoded():
        assert proc.stdout is not None
        try:
            while True:
                chunk = proc.stdout.read(1024 * 256)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    from urllib.parse import quote
    return StreamingResponse(
        iter_transcoded(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(file_path.stem)}.mp3"},
    )


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


def _infer_hints_from_library_path(file_path: str) -> tuple[str, str]:
    """从 library 路径中推出 (artist, album) 作为 hint。

    文件位于 `{library_root}/{artist}/{album}/{track}.ext` 时，父目录=album、
    祖父目录=artist。如果父与祖父同名（刮削失败退化出的重复目录）
    或者文件不在 library 下两层，返回空。
    """
    try:
        path = Path(file_path).resolve()
        library_root = Path(config.paths.library).resolve()
    except Exception:
        return "", ""
    try:
        rel = path.relative_to(library_root)
    except ValueError:
        return "", ""
    parts = rel.parts
    if len(parts) < 3:
        return "", ""
    artist, album = parts[0], parts[1]
    if artist == album:
        return "", ""
    return artist, album


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
        query = db.query(MusicFile)
        if album_artist == UNKNOWN_ARTIST:
            query = query.filter((MusicFile.artist.is_(None)) | (MusicFile.artist == ""))
        else:
            query = query.filter(MusicFile.artist == album_artist)
        if album_name == UNKNOWN_ALBUM:
            query = query.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
        else:
            query = query.filter(MusicFile.album == album_name)
        files = query.all()
    else:
        # Rescrape all unscraped
        files = db.query(MusicFile).filter(MusicFile.scraped == False).limit(50).all()

    if not files:
        return {"ok": True, "message": "没有需要刮削的文件", "scraped": 0, "total": 0}

    scraped_count = 0
    # 在专辑级重刮削时强制专辑/主艺人一致，避免某一首被同名专辑带走
    locked_album = album_name if album_name and album_name != UNKNOWN_ALBUM else ""
    locked_artist = album_artist if album_artist and album_artist != UNKNOWN_ARTIST else ""
    for f in files:
        if not f.file_path or not os.path.exists(f.file_path):
            continue
        title_hint = (f.title or "").strip()
        artist_hint = (f.artist or "").strip() or locked_artist
        album_hint = (f.album or "").strip() or locked_album
        # DB 字段缺失时，从 library 路径 (artist/album/track) 中补，比文件名推断准
        if not artist_hint or not album_hint:
            path_artist, path_album = _infer_hints_from_library_path(f.file_path)
            artist_hint = artist_hint or path_artist
            album_hint = album_hint or path_album
        meta = _scrape_file(
            f.file_path,
            title_hint=title_hint,
            artist_hint=artist_hint,
            album_hint=album_hint,
        )
        if meta:
            # 专辑定锁：保底主艺人与专辑名不被刮削源带偏。
            # 目前 DB 没有 album_artist 字段，library 也是按 artist+album 分组，
            # 所以专辑级重刮削时需要把 DB artist 固定为这张专辑的主艺人，
            # 避免某首歌因 feat./同名候选导致专辑在前端被拆成多张。
            if locked_album and meta.album != locked_album:
                meta.album = locked_album
            if locked_artist:
                meta.album_artist = locked_artist
                meta.artist = locked_artist
            tagged_path = tag_file(f.file_path, meta)
            if isinstance(tagged_path, str) and tagged_path:
                f.file_path = tagged_path
                f.link_path = tagged_path
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


@router.post("/scan")
def scan_library_endpoint(payload: dict = Body(default={})):
    """Import/rescan the configured library directory from local files/tags."""
    from app.config import config
    from app.db import SessionLocal
    from app.services.library_scan import scan_library as _scan_library
    from app.services.scrape_jobs import runner as job_runner

    root = (payload or {}).get("root") or config.paths.library
    remove_missing = bool((payload or {}).get("remove_missing", False))

    def _run(job):
        local_db = SessionLocal()
        try:
            def progress(done: int, total: int, label: str):
                job.total = total
                job.progress = done
                if done % 25 == 0 or done == total:
                    job.summary = {"current": label, "scanned": done, "total": total}
            job.summary = _scan_library(local_db, root=root, remove_missing=remove_missing, progress=progress)
            job.total = job.summary.get("total", job.total)
            job.progress = job.total
        finally:
            local_db.close()

    job = job_runner.submit("library_scan", total=0, runner=_run, step_labels=[])
    return {"ok": True, "job_id": job.id, "root": root}


@router.post("/rescan_metadata")
def rescan_metadata(file_ids: list[int] = [], album_artist: str = "", album_name: str = "",
                    db: Session = Depends(get_db)):
    """Re-read local audio metadata (duration/bitrate/etc.) for a file or whole album."""
    from app.scrapers.tagger import read_audio_metadata

    if file_ids:
        files = db.query(MusicFile).filter(MusicFile.id.in_(file_ids)).all()
    elif album_artist and album_name:
        query = db.query(MusicFile)
        if album_artist == UNKNOWN_ARTIST:
            query = query.filter((MusicFile.artist.is_(None)) | (MusicFile.artist == ""))
        else:
            query = query.filter(MusicFile.artist == album_artist)
        if album_name == UNKNOWN_ALBUM:
            query = query.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
        else:
            query = query.filter(MusicFile.album == album_name)
        files = query.all()
    else:
        files = db.query(MusicFile).filter(
            (MusicFile.duration.is_(None)) | (MusicFile.duration == 0)
        ).limit(500).all()

    updated = 0
    for f in files:
        if not f.file_path or not os.path.exists(f.file_path):
            continue
        try:
            audio_meta = read_audio_metadata(f.file_path)
        except Exception:
            continue
        for k in ("duration", "bitrate", "sample_rate", "channels"):
            v = audio_meta.get(k)
            if v is not None:
                setattr(f, k, v)
        updated += 1
    db.commit()
    return {"ok": True, "updated": updated, "total": len(files)}


@router.post("/rescrape_albums")
def rescrape_albums(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    """Batch rescrape multiple albums. Body: {albums: [{artist, album}], async?: bool}

    Default async=true: enqueue a background job and return its id immediately.
    Pass async=false to keep the legacy synchronous behaviour.
    """
    albums = (payload or {}).get("albums") or []
    is_async = (payload or {}).get("async", True)
    if not albums:
        return {"ok": True, "results": []}

    cleaned = []
    for entry in albums:
        artist = (entry or {}).get("artist")
        album = (entry or {}).get("album")
        if artist and album:
            cleaned.append({"artist": artist, "album": album})
    if not cleaned:
        return {"ok": True, "results": []}

    if not is_async:
        results = []
        for entry in cleaned:
            try:
                res = rescrape_files(file_ids=[], album_artist=entry["artist"], album_name=entry["album"], db=db)
            except Exception as e:
                results.append({**entry, "ok": False, "error": str(e)[:200]})
                continue
            results.append({**entry, **res})
        return {"ok": True, "results": results}

    from app.services.scrape_jobs import runner as job_runner, mark_step
    from app.db import SessionLocal

    step_labels = [f"{e['artist']} · {e['album']}" for e in cleaned]

    def _run(job):
        from app.api.library import rescrape_files as _rescrape
        ok = 0
        scraped_total = 0
        track_total = 0
        local_db = SessionLocal()
        try:
            for idx, entry in enumerate(cleaned):
                step = job.steps[idx]
                step.status = "running"
                try:
                    res = _rescrape(file_ids=[], album_artist=entry["artist"], album_name=entry["album"], db=local_db)
                    scraped = int(res.get("scraped") or 0)
                    total = int(res.get("total") or 0)
                    scraped_total += scraped
                    track_total += total
                    msg = res.get("message") or f"{scraped}/{total}"
                    mark_step(step, "ok" if total else "skipped", msg)
                    ok += 1
                except Exception as e:
                    mark_step(step, "failed", str(e)[:200])
                job.progress = idx + 1
                job.summary = {"ok": ok, "scraped": scraped_total, "tracks": track_total}
        finally:
            local_db.close()

    job = job_runner.submit("rescrape_albums", total=len(cleaned), runner=_run, step_labels=step_labels)
    return {"ok": True, "job_id": job.id, "total": len(cleaned)}


@router.get("/jobs")
def list_jobs(limit: int = 20):
    from app.services.scrape_jobs import runner as job_runner
    return {"jobs": job_runner.list(limit=limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    from app.services.scrape_jobs import runner as job_runner
    job = job_runner.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_dict()


@router.get("/tools")
def list_library_tools():
    """Available library tools (id/label/description)."""
    from app.services.library_tools import list_tools
    return {"tools": list_tools()}


@router.post("/tools/{tool_id}/preview")
def preview_library_tool(tool_id: str, payload: dict = Body(default={})):
    """Run a library tool in dry-run mode and return the proposed changes."""
    from app.services.library_tools import tool_preview, ToolError
    try:
        result = tool_preview(
            tool_id,
            file_ids=payload.get("file_ids") or None,
            album_artist=payload.get("album_artist") or "",
            album_name=payload.get("album_name") or "",
            options=payload.get("options") or {},
        )
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result.to_dict()


@router.post("/tools/{tool_id}/apply")
def apply_library_tool(tool_id: str, payload: dict = Body(default={})):
    """Apply a library tool. Defaults to async via the scrape-job runner."""
    from app.services.library_tools import tool_apply, ToolError
    async_mode = bool(payload.get("async", True))
    try:
        outcome = tool_apply(
            tool_id,
            file_ids=payload.get("file_ids") or None,
            album_artist=payload.get("album_artist") or "",
            album_name=payload.get("album_name") or "",
            options=payload.get("options") or {},
            async_mode=async_mode,
        )
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if async_mode:
        return {"ok": True, "job_id": outcome.id, "total": outcome.total}
    return {"ok": True, "summary": outcome}


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

