"""Library API routes."""
import datetime
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from app.auth import verify_token
from app.config import config
from app.db import get_db
from app.models import LibraryAuditEvent, MusicFile
from app.services.album_identity import primary_artist
from app.services.library_health_rules import has_lyrics, is_missing_lyrics_candidate, cue_split_candidate
from app.scrapers.matcher import text_score

router = APIRouter()

UNKNOWN_ALBUM = "单曲/未知专辑"
UNKNOWN_ARTIST = "Unknown Artist"
_CJK_TEXT_RE = re.compile(r"[\u4e00-\u9fff]")
_ROMAN_TEXT_RE = re.compile(r"[A-Za-z]")


def _has_cjk_text(value: str | None) -> bool:
    return bool(_CJK_TEXT_RE.search(value or ""))


def _looks_romanized(value: str | None) -> bool:
    text = value or ""
    return bool(_ROMAN_TEXT_RE.search(text)) and not _has_cjk_text(text)


def _prefer_display_name(values: list[str]) -> str:
    """Prefer Chinese display identity over romanized aliases for repair suggestions."""
    cleaned = [str(v or "").strip() for v in values if str(v or "").strip()]
    if not cleaned:
        return ""
    cjk = [v for v in cleaned if _has_cjk_text(v)]
    if cjk:
        cjk.sort(key=lambda x: (len(x), cleaned.index(x)))
        return cjk[0]
    return cleaned[0]


def _similar_album_key(album: str | None) -> str:
    album = _display_album(album)
    if _has_cjk_text(album):
        return "cjk:" + re.sub(r"\s+", "", album.lower())
    return "roman:" + re.sub(r"[\s\-_/·.()（）\[\]【】《》<>]+", "", album.lower())


def _display_album(album: str | None) -> str:
    """Return a stable display album for singles or missing album metadata."""
    return album or UNKNOWN_ALBUM


def _display_album_artist(row: MusicFile) -> str:
    """Album grouping artist: albumartist first, then track artist."""
    return (getattr(row, "album_artist", None) or row.artist or UNKNOWN_ARTIST)


def _album_artist_group():
    """SQL expression matching _display_album_artist for grouping/filtering."""
    return func.coalesce(func.nullif(MusicFile.album_artist, ""), func.nullif(MusicFile.artist, ""), UNKNOWN_ARTIST)



def _file_dict(f: MusicFile) -> dict:
    return {
        "id": f.id,
        "task_id": f.task_id,
        "file_path": f.file_path,
        "artist": f.artist or "",
        "album_artist": _display_album_artist(f),
        "album": _display_album(f.album),
        "title": f.title or "",
        "year": f.year,
        "format": f.format or "",
        "scraped": f.scraped,
        "track_number": f.track_number,
        "disc_number": f.disc_number,
        "duration": f.duration or 0,
        "bitrate": f.bitrate,
        "sample_rate": f.sample_rate,
    }

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


def _embedded_cover_data(file_path: str | None) -> bytes | None:
    """Return embedded artwork bytes, if readable."""
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        from app.scrapers.tagger import read_embedded_cover
        return read_embedded_cover(file_path)
    except Exception:
        return None


def _has_cover(file_path: str | None) -> bool:
    """Cover availability used by API/UI health checks: sidecar first, then embedded artwork."""
    return bool(file_path and (_album_cover_path(file_path) or _embedded_cover_data(file_path)))


def _cover_response(file_path: str | None):
    """Serve sidecar cover, falling back to embedded artwork bytes."""
    if not file_path:
        raise HTTPException(status_code=404, detail="No cover")
    cover = _album_cover_path(file_path)
    if cover:
        return FileResponse(cover)
    data = _embedded_cover_data(file_path)
    if not data:
        raise HTTPException(status_code=404, detail="No cover")
    head = data[:12]
    media_type = "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        media_type = "image/png"
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        media_type = "image/webp"
    return Response(content=data, media_type=media_type)


@router.get("/")
def list_library(artist: str = "", album: str = "", q: str = "", limit: int = 50,
                 db: Session = Depends(get_db)):
    """Browse music library."""
    query = db.query(MusicFile).order_by(MusicFile.created_at.desc())
    if artist:
        like_artist = f"%{artist}%"
        query = query.filter((MusicFile.artist.ilike(like_artist)) | (MusicFile.album_artist.ilike(like_artist)))
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
            (MusicFile.album_artist.ilike(like)) |
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
            "album_artist": _display_album_artist(f),
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
            "has_cover": _has_cover(f.file_path),
        }
        for f in files
    ]


@router.get("/files")
def list_files(
    q: str = "",
    album_artist: str = "",
    album_name: str = "",
    limit: int = 50,
    offset: int = 0,
    sort: str = "track",
    db: Session = Depends(get_db),
):
    """Paginated file listing with search. Powers the tools modal file picker."""
    query = db.query(MusicFile)
    if album_artist:
        query = query.filter(_album_artist_group().ilike(f"%{album_artist}%"))
    if album_name:
        if album_name == UNKNOWN_ALBUM:
            query = query.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
        else:
            query = query.filter(MusicFile.album.ilike(f"%{album_name}%"))
    if q:
        like = f"%{q}%"
        query = query.filter(
            (MusicFile.title.ilike(like)) |
            (MusicFile.artist.ilike(like)) |
            (MusicFile.album_artist.ilike(like)) |
            (MusicFile.album.ilike(like)) |
            (MusicFile.file_path.ilike(like))
        )
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = query.count()
    if sort == "title":
        query = query.order_by(MusicFile.title.is_(None), MusicFile.title.asc(), MusicFile.id.asc())
    elif sort == "artist":
        query = query.order_by(MusicFile.artist.is_(None), MusicFile.artist.asc(), MusicFile.id.asc())
    elif sort == "duration":
        query = query.order_by(MusicFile.duration.is_(None), MusicFile.duration.desc(), MusicFile.id.asc())
    elif sort == "size":
        query = query.order_by(MusicFile.bitrate.is_(None), MusicFile.bitrate.desc(), MusicFile.id.asc())
    else:
        query = query.order_by(
            MusicFile.track_number.is_(None),
            MusicFile.track_number.asc(),
            MusicFile.disc_number.is_(None),
            MusicFile.disc_number.asc(),
            MusicFile.id.asc(),
        )
    files = query.offset(offset).limit(limit).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_file_dict(f) for f in files],
    }


@router.get("/albums")
def list_albums(artist: str = "", q: str = "", sort: str = "updated", limit: int = 200, offset: int = 0,
                db: Session = Depends(get_db)):
    """List unique albums grouped by (album_artist, album), with library-friendly stats."""
    artist_group = _album_artist_group()
    album_group = func.coalesce(func.nullif(MusicFile.album, ""), UNKNOWN_ALBUM)
    latest_at = func.max(MusicFile.created_at)
    track_count = func.count(MusicFile.id)
    query = (
        db.query(
            artist_group.label("artist"),
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
        .group_by(artist_group, album_group)
    )
    if artist:
        like_artist = f"%{artist}%"
        query = query.filter((MusicFile.artist.ilike(like_artist)) | (MusicFile.album_artist.ilike(like_artist)))
    if q:
        query = query.filter(
            (MusicFile.album.ilike(f"%{q}%")) |
            (MusicFile.artist.ilike(f"%{q}%")) |
            (MusicFile.album_artist.ilike(f"%{q}%")) |
            (MusicFile.title.ilike(f"%{q}%"))
        )

    total = query.count()

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    sort_map = {
        "updated": latest_at.desc(),
        "name": album_group.asc(),
        "artist": artist_group.asc(),
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
            "has_cover": _has_cover(r.sample_path),
            "sample_id": r.sample_id,
        })
    return {"total": total, "offset": offset, "limit": limit, "items": result}


@router.get("/album-tracks")
def list_album_tracks(artist: str, album: str, db: Session = Depends(get_db)):
    """List tracks in a specific album."""
    query = db.query(MusicFile)
    artist_group = _album_artist_group()
    if artist == UNKNOWN_ARTIST:
        query = query.filter(artist_group == UNKNOWN_ARTIST)
    else:
        query = query.filter(artist_group == artist)
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
            "album_artist": _display_album_artist(f),
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
    """Serve cover image for a music file: sidecar first, embedded artwork second."""
    f = db.query(MusicFile).filter(MusicFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    return _cover_response(f.file_path)


@router.get("/album-cover")
def get_album_cover(artist: str, album: str, db: Session = Depends(get_db)):
    """Serve cover for an album by (album_artist, album)."""
    query = db.query(MusicFile)
    artist_group = _album_artist_group()
    if artist == UNKNOWN_ARTIST:
        query = query.filter(artist_group == UNKNOWN_ARTIST)
    else:
        query = query.filter(artist_group == artist)
    if album == UNKNOWN_ALBUM:
        query = query.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
    else:
        query = query.filter(MusicFile.album == album)
    f = query.first()
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    return _cover_response(f.file_path)


def _has_lrc(file_path: str | None) -> bool:
    return has_lyrics(file_path)


def _is_unknown_artist(artist: str | None) -> bool:
    if not artist:
        return True
    a = artist.strip().lower()
    return a in {"", "unknown artist", "未知艺人", "unknown", "various artists"}


def _library_path_album_artist(file_path: str | None) -> str:
    """Infer album artist from configured library path: {artist}/{album}/{track}."""
    if not file_path:
        return ""
    try:
        rel = Path(file_path).resolve().relative_to(Path(config.paths.library).resolve())
    except Exception:
        return ""
    parts = rel.parts
    if len(parts) < 3 or parts[0] == parts[1]:
        return ""
    return parts[0]


def _album_artist_conflict_items(files: list[MusicFile], limit: int) -> tuple[int, list[dict]]:
    """Find physical album folders whose rows disagree on album_artist.

    This catches old libraries where rows were backfilled from track artist and
    one album now appears split because of feat./guest artists. Grouping by
    physical parent folder avoids false positives from same-named albums by
    different artists.
    """
    groups: dict[str, dict] = {}
    for f in files:
        if not f.file_path:
            continue
        try:
            folder = str(Path(f.file_path).parent)
        except Exception:
            continue
        bucket = groups.setdefault(folder, {"files": [], "artists": set(), "album": f.album or "", "suggested": ""})
        bucket["files"].append(f)
        aa = (f.album_artist or f.artist or "").strip()
        if aa:
            bucket["artists"].add(aa)
        if not bucket.get("album") and f.album:
            bucket["album"] = f.album
        if not bucket.get("suggested"):
            bucket["suggested"] = _library_path_album_artist(f.file_path)
    items = []
    total_tracks = 0
    for folder, bucket in groups.items():
        artists = sorted(bucket["artists"])
        rows = bucket["files"]
        if len(rows) < 2 or len(artists) <= 1:
            continue
        sample = rows[0]
        suggested = bucket.get("suggested") or artists[0]
        total_tracks += len(rows)
        items.append({
            "artist": suggested or UNKNOWN_ARTIST,
            "album": _display_album(bucket.get("album") or sample.album),
            "track_count": len(rows),
            "sample_track_id": sample.id,
            "sample_path": sample.file_path,
            "has_cover": _has_cover(sample.file_path),
            "file_ids": [r.id for r in rows],
            "artists": artists,
            "suggested_album_artist": suggested,
            "folder": folder,
        })
    items.sort(key=lambda x: (x["track_count"], len(x.get("artists") or [])), reverse=True)
    return total_tracks, items[:limit]


def _split_album_folder_items(files: list[MusicFile], limit: int) -> tuple[int, list[dict]]:
    """Find album folders split by artist or Chinese/romanized album aliases."""
    raw_groups: dict[str, dict] = {}
    for f in files:
        album = _display_album(f.album)
        key = _similar_album_key(album)
        if not key:
            continue
        bucket = raw_groups.setdefault(key, {"album": album, "files": [], "folders": set(), "artists": set(), "albums": set()})
        bucket["files"].append(f)
        bucket["albums"].add(album)
        if f.file_path:
            try:
                p = Path(f.file_path).resolve()
                bucket["folders"].add(str(p.parent))
            except Exception:
                pass
        aa = (f.album_artist or f.artist or "").strip()
        if aa:
            bucket["artists"].add(aa)

    # Merge romanized groups into nearby CJK album groups when track titles/artists
    # overlap. This catches historical `魔杰座` + `Capricorn` style splits.
    groups = list(raw_groups.values())
    cjk_groups = [g for g in groups if any(_has_cjk_text(a) for a in g["albums"])]
    merged: list[dict] = []
    consumed: set[int] = set()
    for idx, group in enumerate(groups):
        if idx in consumed:
            continue
        target = group
        if not any(_has_cjk_text(a) for a in group["albums"]):
            best_idx = -1
            best_score = 0.0
            titles = [r.title or Path(r.file_path or "").stem for r in group["files"]]
            artists = [r.album_artist or r.artist or "" for r in group["files"]]
            for c_idx, cjk in enumerate(cjk_groups):
                overlap_titles = max((text_score(t, ct.title or Path(ct.file_path or "").stem) for t in titles for ct in cjk["files"]), default=0.0)
                overlap_artists = max((text_score(a, ca.album_artist or ca.artist) for a in artists for ca in cjk["files"]), default=0.0)
                duration_hits = 0
                duration_pairs = 0
                for r in group["files"]:
                    for cr in cjk["files"]:
                        if r.track_number and cr.track_number and r.track_number != cr.track_number:
                            continue
                        if r.duration and cr.duration:
                            duration_pairs += 1
                            if abs(float(r.duration) - float(cr.duration)) <= 5:
                                duration_hits += 1
                duration_score = (duration_hits / duration_pairs) if duration_pairs else 0.0
                score = max(overlap_titles * 0.7 + overlap_artists * 0.3, duration_score * 0.75 + overlap_artists * 0.25)
                if score > best_score:
                    best_score, best_idx = score, c_idx
            if best_idx >= 0 and best_score >= 0.62:
                target = cjk_groups[best_idx]
        if target is not group:
            target["files"].extend(group["files"])
            target["folders"].update(group["folders"])
            target["artists"].update(group["artists"])
            target["albums"].update(group["albums"])
            consumed.add(idx)
        else:
            merged.append(group)

    items = []
    total_tracks = 0
    seen_ids: set[int] = set()
    for bucket in merged:
        rows = sorted({r.id: r for r in bucket["files"]}.values(), key=lambda r: (r.track_number is None, r.track_number or 9999, r.id))
        if len(rows) < 2:
            continue
        folders = sorted(bucket["folders"])
        artists = sorted(bucket["artists"])
        albums = sorted(bucket["albums"])
        if len(folders) <= 1 and len(artists) <= 1 and len(albums) <= 1:
            continue
        sample = rows[0]
        suggested_artist = _prefer_display_name(artists) or primary_artist(sample.album_artist or sample.artist) or _library_path_album_artist(sample.file_path) or _display_album_artist(sample)
        suggested_album = _prefer_display_name(albums) or bucket["album"]
        total_tracks += len(rows)
        seen_ids.update(r.id for r in rows)
        items.append({
            "artist": suggested_artist or UNKNOWN_ARTIST,
            "album": suggested_album,
            "track_count": len(rows),
            "sample_track_id": sample.id,
            "sample_path": sample.file_path,
            "has_cover": _has_cover(sample.file_path),
            "file_ids": [r.id for r in rows],
            "artists": artists,
            "albums": albums,
            "folders": folders,
            "suggested_album_artist": suggested_artist,
            "suggested_album": suggested_album,
        })
    items.sort(key=lambda x: (len(x.get("folders") or []), len(x.get("albums") or []), x["track_count"]), reverse=True)
    return total_tracks, items[:limit]


_HEALTH_KINDS = ("missing_cover", "missing_lyrics", "missing_duration", "unknown_artist", "unscraped", "cue_candidates", "album_artist_conflicts", "split_album_folders")


@router.get("/health")
def library_health(kind: str = "", limit: int = 100, db: Session = Depends(get_db)):
    """Report library hygiene issues grouped by album."""
    files = db.query(MusicFile).all()
    limit = max(1, min(limit, 1000))
    buckets: dict[str, dict[tuple[str, str], dict]] = {k: {} for k in _HEALTH_KINDS}
    totals = {k: 0 for k in _HEALTH_KINDS}

    def _has_cue(f: MusicFile) -> bool:
        return cue_split_candidate(f.file_path, duration=f.duration)

    def _add(bucket_key: str, f: MusicFile):
        artist = _display_album_artist(f)
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
                "has_cover": _has_cover(f.file_path),
            }
        bucket[key]["track_count"] += 1
        totals[bucket_key] += 1

    for f in files:
        if not _has_cover(f.file_path):
            _add("missing_cover", f)
        if is_missing_lyrics_candidate(
            f.file_path,
            title=f.title or "",
            artist=f.artist or f.album_artist or "",
            album=f.album or "",
            genre=f.genre or "",
            duration=f.duration,
            scraped=f.scraped,
        ):
            _add("missing_lyrics", f)
        if not f.duration or f.duration <= 0:
            _add("missing_duration", f)
        if _is_unknown_artist(f.album_artist or f.artist):
            _add("unknown_artist", f)
        if not f.scraped:
            _add("unscraped", f)
        if _has_cue(f):
            _add("cue_candidates", f)

    conflict_total, conflict_items = _album_artist_conflict_items(files, limit)
    totals["album_artist_conflicts"] = conflict_total
    split_total, split_items = _split_album_folder_items(files, limit)
    totals["split_album_folders"] = split_total

    def _serialize(bucket_key: str):
        if bucket_key == "album_artist_conflicts":
            return conflict_items
        if bucket_key == "split_album_folders":
            return split_items
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
    artist_group = _album_artist_group()
    artists = db.query(artist_group).distinct().count()
    album_group = func.coalesce(func.nullif(MusicFile.album, ""), UNKNOWN_ALBUM)
    albums = db.query(artist_group, album_group).distinct().count()
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
        "album_artist": _display_album_artist(f),
        "album": _display_album(f.album),
        "title": f.title,
        "year": f.year,
        "genre": f.genre,
        "format": f.format,
        "scraped": f.scraped,
        "has_cover": _has_cover(f.file_path),
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


def _normalize_file_ids(value: Any) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
        out = []
        for p in parts:
            try:
                out.append(int(p))
            except ValueError:
                continue
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out
    return []


def _normalize_library_selection(payload: Any, file_ids: list[int] | None, album_artist: str, album_name: str) -> tuple[list[int], str, str]:
    """Accept query params, raw-list bodies, and legacy dict bodies."""
    ids = _normalize_file_ids(file_ids)
    artist = album_artist or ""
    album = album_name or ""
    if isinstance(payload, list):
        ids = ids or _normalize_file_ids(payload)
    elif isinstance(payload, dict):
        ids = ids or _normalize_file_ids(payload.get("file_ids"))
        artist = artist or payload.get("album_artist") or payload.get("artist") or ""
        album = album or payload.get("album_name") or payload.get("album") or ""
    return ids, artist, album


@router.post("/rescrape")
def rescrape_files(payload: Any = Body(default=None), file_ids: list[int] | None = Query(default=None),
                  album_artist: str = "", album_name: str = "", db: Session = Depends(get_db)):
    """Re-scrape metadata for specified files or an entire album."""
    from app.services.pipeline import _scrape_file, _enrich_from_local_assets
    from app.scrapers.tagger import tag_file, save_lyrics, save_cover, read_audio_metadata, read_existing_tags

    file_ids, album_artist, album_name = _normalize_library_selection(payload, file_ids, album_artist, album_name)

    # Get files to rescrape
    if file_ids:
        files = db.query(MusicFile).filter(MusicFile.id.in_(file_ids)).all()
    elif album_artist and album_name:
        query = db.query(MusicFile)
        artist_group = _album_artist_group()
        if album_artist == UNKNOWN_ARTIST:
            query = query.filter(artist_group == UNKNOWN_ARTIST)
        else:
            query = query.filter(artist_group == album_artist)
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
        local_tags = read_existing_tags(f.file_path)
        path_artist, path_album = _infer_hints_from_library_path(f.file_path)
        title_hint = (f.title or local_tags.get("title") or Path(f.file_path).stem or "").strip()
        artist_hint = locked_artist or (f.artist or local_tags.get("artist") or local_tags.get("album_artist") or path_artist or "").strip()
        album_hint = locked_album or (f.album or local_tags.get("album") or path_album or "").strip()
        audio_meta_hint = read_audio_metadata(f.file_path)
        meta = _scrape_file(
            f.file_path,
            title_hint=title_hint,
            artist_hint=artist_hint,
            album_hint=album_hint,
            year_hint=local_tags.get("year") or f.year,
            duration_hint=audio_meta_hint.get("duration") or f.duration,
            track_hint=local_tags.get("track_number") or f.track_number,
        )
        if meta:
            _enrich_from_local_assets(f.file_path, meta)
        if meta:
            # 专辑定锁：保底主艺人与专辑名不被刮削源带偏。
            # track artist 保留单曲艺人/feat. 信息；前端按 album_artist + album 分组。
            if locked_album and meta.album != locked_album:
                meta.album = locked_album
            if locked_artist:
                meta.album_artist = locked_artist
            tagged_path = tag_file(f.file_path, meta)
            if isinstance(tagged_path, str) and tagged_path:
                f.file_path = tagged_path
                f.link_path = tagged_path
            if meta.lyrics:
                save_lyrics(f.file_path, meta.lyrics)
            if meta.cover_data:
                save_cover(str(Path(f.file_path).parent), meta.cover_data)
            f.artist = meta.artist
            f.album_artist = meta.album_artist or meta.artist
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
def rescan_metadata(payload: Any = Body(default=None), file_ids: list[int] | None = Query(default=None),
                    album_artist: str = "", album_name: str = "", db: Session = Depends(get_db)):
    """Re-read local audio metadata (duration/bitrate/etc.) for a file or whole album."""
    from app.scrapers.tagger import read_audio_metadata

    file_ids, album_artist, album_name = _normalize_library_selection(payload, file_ids, album_artist, album_name)

    if file_ids:
        files = db.query(MusicFile).filter(MusicFile.id.in_(file_ids)).all()
    elif album_artist and album_name:
        query = db.query(MusicFile)
        artist_group = _album_artist_group()
        if album_artist == UNKNOWN_ARTIST:
            query = query.filter(artist_group == UNKNOWN_ARTIST)
        else:
            query = query.filter(artist_group == album_artist)
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


def _norm_text(value: str | None) -> str:
    import re
    text = (value or "").lower()
    text = re.sub(r"[\s\-_·•.,，。:：;；'\"“”‘’()（）\[\]【】]+", "", text)
    return text


def _norm_title(value: str | None) -> str:
    import re
    text = (value or "").lower()
    text = re.sub(r"[\(（\[【].*?(live|cover|翻唱|remix|伴奏|karaoke|demo|版|现场).*?[\)）\]】]", "", text, flags=re.I)
    text = re.sub(r"[-_·•]\s*(live|cover|翻唱|remix|伴奏|karaoke|demo|.*版|现场).*$", "", text, flags=re.I)
    return _norm_text(text)


def _norm_song_key(title: str | None, artist: str | None = "") -> str:
    return f"{_norm_title(title)}::{_norm_text((artist or '').split('/')[0])}"


def _is_cover_like(song: dict) -> bool:
    blob = " ".join(str(song.get(k) or "") for k in ("title", "album", "artist", "filename", "subtitle", "remark")).lower()
    return any(term in blob for term in ["翻唱", "cover", "remix", "伴奏", "karaoke", "demo", "live", "现场"])


def _album_looks_complete(files: list[MusicFile]) -> bool:
    tracks = sorted({int(f.track_number) for f in files if f.track_number and int(f.track_number) > 0})
    if len(files) >= 1 and tracks:
        return tracks == list(range(1, max(tracks) + 1)) and max(tracks) <= len(files)
    return False


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _quality_score(song: dict) -> tuple[int, int, int]:
    fmt = (song.get("format") or "").lower()
    url = (song.get("url") or "").lower()
    lossless = 1 if fmt in {"flac", "wav", "ape"} or any(x in url for x in (".flac", ".wav", ".ape")) else 0
    bitrate = int(song.get("bitrate") or 0)
    size = int(song.get("size") or 0)
    return (lossless, bitrate, size)


def _completion_confidence(song: dict, artist: str, album: str) -> dict:
    """Human-readable confidence for album completion candidates.

    Filtering is already deliberately strict before this point. The score is used
    for UI defaults/explanation rather than for allowing risky candidates.
    """
    reasons: list[str] = []
    score = 45
    if _norm_text(song.get("album")) == _norm_text(album):
        score += 25
        reasons.append("专辑名精确匹配")
    song_artist = song.get("artist") or ""
    if not song_artist:
        score += 5
        reasons.append("来源未给艺人，沿用专辑艺人")
    elif _norm_text(artist) in _norm_text(song_artist) or _norm_text(song_artist) in _norm_text(artist):
        score += 15
        reasons.append("艺人匹配")
    fmt = (song.get("format") or "").lower()
    if fmt in {"flac", "wav", "ape"}:
        score += 10
        reasons.append("无损资源")
    elif int(song.get("bitrate") or 0) >= 320:
        score += 5
        reasons.append("高码率")
    source = song.get("source") or ""
    if source in {"qq", "migu", "kugou", "netease", "kuwo"}:
        score += 3
        reasons.append(f"来源：{source}")
    score = max(0, min(100, score))
    if score >= 90:
        label = "很高"
    elif score >= 75:
        label = "高"
    elif score >= 60:
        label = "中"
    else:
        label = "低"
    return {"confidence": score, "confidence_label": label, "confidence_reasons": reasons, "recommended": score >= 75}


@router.post("/album-complete")
def complete_album(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    """Find and optionally download missing local album tracks from online sources.

    This is a pragmatic first pass: search by album artist + album, prefer lossless
    candidates, skip songs already present in the local album, and download the
    best unique candidates when dry_run=false.
    """
    artist = (payload.get("artist") or payload.get("album_artist") or "").strip()
    album = (payload.get("album") or payload.get("album_name") or "").strip()
    dry_run = _bool_value(payload.get("dry_run"), True)
    limit = max(5, min(int(payload.get("limit") or 30), 80))
    sources = payload.get("sources") or ["qq", "migu", "kugou", "netease", "kuwo"]
    if not artist or not album:
        raise HTTPException(status_code=400, detail="artist and album are required")

    existing = db.query(MusicFile).filter(
        _album_artist_group() == artist,
        func.coalesce(MusicFile.album, UNKNOWN_ALBUM) == album,
    ).all()
    existing_keys = {_norm_song_key(f.title or Path(f.file_path or "").stem, f.artist or f.album_artist or artist) for f in existing}
    existing_titles = {_norm_title(f.title or Path(f.file_path or "").stem or "") for f in existing}
    allow_extra = _bool_value(payload.get("allow_extra"), False)
    if _album_looks_complete(existing) and not allow_extra:
        return {
            "ok": True,
            "dry_run": dry_run,
            "existing": len(existing),
            "candidates": [],
            "downloaded": [],
            "reason": "本地曲目编号已连续，判断专辑已完整；如确需额外版本可传 allow_extra=true。",
        }

    from app.services.online_music import search_online, download_online_song
    from app.services.pipeline import _process_completed_torrent
    from app.models import DownloadTask
    import uuid

    selected_candidate_payloads = payload.get("selected_candidates") or []
    if not dry_run and selected_candidate_payloads:
        raw = [dict(r) for r in selected_candidate_payloads if isinstance(r, dict)]
    else:
        rows = search_online(f"{artist} {album}", sources=sources, limit=limit)
        raw = [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in rows]
    candidates: dict[str, dict] = {}
    for song in raw:
        title = (song.get("title") or "").strip()
        if not title or song.get("disabled") or _is_cover_like(song):
            continue
        song_album = (song.get("album") or "").strip()
        song_artist = (song.get("artist") or "").strip()
        album_match = bool(song_album) and _norm_text(song_album) == _norm_text(album)
        artist_match = (not song_artist) or _norm_text(artist) in _norm_text(song_artist) or _norm_text(song_artist) in _norm_text(artist)
        # Be deliberately conservative: album completion should only trust exact
        # album matches. Sources that omit album are too noisy and often return covers.
        if not album_match or not artist_match:
            continue
        title_key = _norm_title(title)
        key = _norm_song_key(title, song_artist or artist)
        if key in existing_keys or title_key in existing_titles:
            continue
        song["album"] = song_album or album
        song["artist"] = song_artist or artist
        song["title"] = title
        current = candidates.get(title_key)
        if not current or _quality_score(song) > _quality_score(current):
            candidates[title_key] = song

    items = sorted(candidates.values(), key=_quality_score, reverse=True)
    for idx, song in enumerate(items):
        song["candidate_id"] = song.get("candidate_id") or f"{idx}:{_norm_title(song.get('title'))}:{song.get('source') or ''}:{song.get('song_id') or song.get('id') or ''}"
        song.update(_completion_confidence(song, artist, album))
    if dry_run:
        return {"ok": True, "dry_run": True, "existing": len(existing), "candidates": items, "downloaded": []}

    selected_ids = set(str(x) for x in (payload.get("candidate_ids") or payload.get("selected_ids") or []) if x is not None)
    selected_titles = {_norm_title(str(x)) for x in (payload.get("titles") or payload.get("selected_titles") or []) if x}
    download_items = items
    if selected_ids or selected_titles:
        download_items = [s for s in items if str(s.get("candidate_id")) in selected_ids or _norm_title(s.get("title")) in selected_titles]

    downloaded = []
    errors = []
    for song in download_items[:limit]:
        try:
            file_path = download_online_song(song)
            synthetic_hash = f"online:{uuid.uuid4().hex}"
            task = DownloadTask(
                torrent_name=song.get("title") or song.get("filename") or "online-music",
                torrent_hash=synthetic_hash,
                site=song.get("source") or "online",
                size=float(song.get("size") or 0),
                status="downloaded",
                save_path=file_path,
            )
            db.add(task)
            db.commit()
            _process_completed_torrent({
                "hash": synthetic_hash,
                "name": task.torrent_name,
                "content_path": file_path,
                "metadata": {
                    "source": song.get("source") or "online",
                    "song_id": song.get("song_id") or "",
                    "title": song.get("title") or task.torrent_name,
                    "artist": song.get("artist") or artist,
                    "album": song.get("album") or album,
                    "duration": song.get("duration") or 0,
                },
            })
            added_rows = db.query(MusicFile).filter(MusicFile.task_id == task_id).all()
            downloaded.append({
                "title": song.get("title"),
                "artist": song.get("artist"),
                "format": song.get("format"),
                "source": song.get("source"),
                "file_path": file_path,
                "task_id": task_id,
                "file_ids": [r.id for r in added_rows],
                "library_paths": [r.file_path for r in added_rows],
            })
        except Exception as exc:
            db.rollback()
            errors.append({"title": song.get("title"), "error": str(exc)[:300]})
    return {"ok": True, "dry_run": False, "existing": len(existing), "candidates": items, "downloaded": downloaded, "errors": errors}


@router.post("/album-complete/undo")
def undo_complete_album(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    """Undo album-complete downloads by moving added library files to trash.

    Accepts task_ids returned by /album-complete, or explicit file_ids/file_paths.
    This is intentionally conservative: it only touches MusicFile rows that match
    those identifiers and uses the existing trash mode instead of permanent delete.
    """
    task_ids = [int(x) for x in (payload.get("task_ids") or []) if str(x).strip().isdigit()]
    file_ids = [int(x) for x in (payload.get("file_ids") or []) if str(x).strip().isdigit()]
    file_paths = [str(x) for x in (payload.get("file_paths") or []) if x]
    dry_run = _bool_value(payload.get("dry_run"), False)
    if not task_ids and not file_ids and not file_paths:
        raise HTTPException(status_code=400, detail="task_ids, file_ids or file_paths are required")

    q = db.query(MusicFile)
    filters = []
    if task_ids:
        filters.append(MusicFile.task_id.in_(task_ids))
    if file_ids:
        filters.append(MusicFile.id.in_(file_ids))
    if file_paths:
        filters.append(MusicFile.file_path.in_(file_paths))
    from sqlalchemy import or_
    files = q.filter(or_(*filters)).all()
    if not files:
        return {"ok": True, "dry_run": dry_run, "matched": 0, "preview": [], "result": None, "reason": "没有匹配到可撤销的入库文件"}

    from app.services.library_tools import delete_files as delete_files_tool
    options = {"delete_files": True, "delete_empty_dirs": True, "delete_missing_db_rows": True, "mode": "trash"}
    if dry_run:
        preview = delete_files_tool.preview(db, files, options)
        return {"ok": True, "dry_run": True, "matched": len(files), "preview": [item.to_dict() for item in preview.items], "summary": preview.summary}

    progress = []
    result = delete_files_tool.apply(db, files, options, lambda idx, msg: progress.append({"idx": idx, "message": msg}))
    if task_ids:
        from app.models import DownloadTask
        try:
            db.query(DownloadTask).filter(DownloadTask.id.in_(task_ids)).update({"status": "undone"}, synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
    return {"ok": True, "dry_run": False, "matched": len(files), "result": result, "progress": progress}


@router.get("/trash")
def list_library_trash(limit: int = 200):
    """List files in the library .trash folder, newest first."""
    root = Path(config.paths.library).resolve()
    trash_root = root / ".trash"
    items = []
    if trash_root.exists():
        for p in trash_root.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(trash_root)
                parts = rel.parts
                restore_rel = Path(*parts[1:]) if len(parts) >= 2 and parts[0].isdigit() else rel
                stat = p.stat()
                items.append({
                    "trash_path": str(p),
                    "relative_path": str(rel),
                    "restore_path": str(root / restore_rel),
                    "restore_exists": (root / restore_rel).exists(),
                    "filename": p.name,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
            except Exception:
                continue
    items.sort(key=lambda x: x.get("mtime") or 0, reverse=True)
    return {"items": items[:limit], "total": len(items), "trash_root": str(trash_root)}


def _trash_restore_plan(root: Path, trash_root: Path, trash_path_value: str) -> dict:
    trash_path = Path(str(trash_path_value or "")).resolve()
    try:
        rel = trash_path.relative_to(trash_root.resolve())
    except Exception:
        raise HTTPException(status_code=400, detail="invalid trash_path")
    if not trash_path.is_file():
        raise HTTPException(status_code=404, detail="trash file not found")
    parts = rel.parts
    restore_rel = Path(*parts[1:]) if len(parts) >= 2 and parts[0].isdigit() else rel
    restore_path = (root / restore_rel).resolve()
    try:
        restore_path.relative_to(root)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid restore target")
    return {
        "trash_path": trash_path,
        "relative_path": str(rel),
        "restore_path": restore_path,
        "restore_exists": restore_path.exists(),
    }


def _conflict_backup_path(root: Path, trash_root: Path, restore_path: Path) -> Path:
    """Return a unique backup path for an existing restore target.

    Overwrite restore must never discard a real music file. If the target exists,
    move it into .trash/restore-conflicts first, then restore the requested file.
    """
    rel = restore_path.relative_to(root)
    dest = trash_root / "restore-conflicts" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S") / rel
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    idx = 1
    while True:
        candidate = dest.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def _restore_one_trash_file(root: Path, trash_root: Path, trash_path_value: str, overwrite: bool = False, dry_run: bool = False) -> dict:
    plan = _trash_restore_plan(root, trash_root, trash_path_value)
    trash_path: Path = plan["trash_path"]
    restore_path: Path = plan["restore_path"]
    backup_path = None
    if restore_path.exists():
        if not overwrite:
            raise HTTPException(status_code=409, detail="restore target already exists")
        backup_path = _conflict_backup_path(root, trash_root, restore_path)
    if dry_run:
        return {
            "trash_path": str(trash_path),
            "restored_path": str(restore_path),
            "restore_exists": plan["restore_exists"],
            "would_backup_path": str(backup_path) if backup_path else None,
            "dry_run": True,
        }
    restore_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(restore_path), str(backup_path))
        from app.services.library_audit import log_library_event
        log_library_event(action="restore_conflict_backup", file_path=str(restore_path), trash_path=str(backup_path), message="恢复覆盖前备份已存在目标")
    shutil.move(str(trash_path), str(restore_path))
    from app.services.library_audit import log_library_event
    log_library_event(action="restore", trash_path=str(trash_path), restore_path=str(restore_path), message="从音乐库回收站恢复文件", details={"backup_path": str(backup_path) if backup_path else None})
    for parent in list(trash_path.parents):
        if parent == trash_root or parent == root or trash_root not in parent.parents:
            break
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            break
    return {"trash_path": str(trash_path), "restored_path": str(restore_path), "backup_path": str(backup_path) if backup_path else None}


@router.post("/trash/restore")
def restore_library_trash(payload: dict = Body(default={})):
    """Restore one file from .trash to its original library-relative path."""
    root = Path(config.paths.library).resolve()
    trash_root = root / ".trash"
    result = _restore_one_trash_file(
        root,
        trash_root,
        str(payload.get("trash_path") or ""),
        bool(payload.get("overwrite")),
        _bool_value(payload.get("dry_run"), False),
    )
    return {"ok": True, **result}


@router.post("/trash/restore_many")
def restore_many_library_trash(payload: dict = Body(default={})):
    """Restore multiple files from .trash. Each file is moved back to its original path."""
    root = Path(config.paths.library).resolve()
    trash_root = root / ".trash"
    paths = [str(x) for x in (payload.get("trash_paths") or []) if x]
    if not paths:
        raise HTTPException(status_code=400, detail="trash_paths is required")
    restored = []
    errors = []
    for p in paths[:200]:
        try:
            restored.append(_restore_one_trash_file(
                root,
                trash_root,
                p,
                bool(payload.get("overwrite")),
                _bool_value(payload.get("dry_run"), False),
            ))
        except HTTPException as exc:
            errors.append({"trash_path": p, "error": exc.detail})
        except Exception as exc:
            errors.append({"trash_path": p, "error": str(exc)[:300]})
    return {"ok": not errors, "restored": restored, "errors": errors, "total": len(paths)}


@router.get("/audit")
def list_library_audit(limit: int = 100, action: str = "", db: Session = Depends(get_db)):
    """List recent library delete/trash/restore audit events."""
    limit = max(1, min(int(limit or 100), 500))
    q = db.query(LibraryAuditEvent)
    if action:
        q = q.filter(LibraryAuditEvent.action == action)
    rows = q.order_by(LibraryAuditEvent.id.desc()).limit(limit).all()
    items = []
    import json
    for r in rows:
        try:
            details = json.loads(r.details_json or "{}")
        except Exception:
            details = {}
        items.append({
            "id": r.id,
            "action": r.action,
            "status": r.status,
            "file_path": r.file_path,
            "trash_path": r.trash_path,
            "restore_path": r.restore_path,
            "message": r.message,
            "details": details,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"items": items, "total": len(items)}


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
def update_file_tags(file_id: int, title: str = "", artist: str = "", album_artist: str = "", album: str = "",
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
    if album_artist:
        f.album_artist = album_artist
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
            if album_artist:
                audio["albumartist"] = album_artist
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

