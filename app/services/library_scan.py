"""Lightweight library scanner/importer.

Scans an existing library directory, reads local tags/technical metadata, and
upserts MusicFile rows without invoking online scrapers. This borrows the useful
part of MTW's scan idea while keeping music-sub's flat MusicFile model.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.config import config
from app.models import MusicFile
from app.organizer.hardlinker import AUDIO_EXTENSIONS
from app.scrapers.tagger import read_audio_metadata, read_existing_tags, read_sidecar_lyrics, find_local_cover_data, read_embedded_cover

logger = logging.getLogger(__name__)


def iter_audio_files(root: str | Path) -> Iterable[Path]:
    base = Path(root)
    if base.is_file():
        if base.suffix.lower() in AUDIO_EXTENSIONS:
            yield base
        return
    if not base.exists():
        return
    skip_dirs = {".git", "@eaDir", "#recycle", ".trash", ".originals"}
    for current, dirs, files in __import__("os").walk(base):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for name in files:
            path = Path(current) / name
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                yield path


def _infer_from_path(path: Path, root: Path) -> dict:
    try:
        rel = path.relative_to(root)
    except Exception:
        rel = path
    parts = rel.parts
    out: dict = {"title": path.stem}
    if len(parts) >= 3:
        out["artist"] = parts[-3]
        out["album"] = parts[-2]
    elif len(parts) >= 2:
        out["album"] = parts[-2]
    return out


def _clean_track_title(title: str) -> tuple[int, str]:
    import re
    m = re.match(r"^\s*(\d{1,3})\s*[.\-_ )、．]+\s*(.+)$", title or "")
    if not m:
        return 0, title
    return int(m.group(1)), m.group(2).strip()


def upsert_file_from_local(db: Session, file_path: str | Path, root: str | Path | None = None) -> tuple[MusicFile, bool]:
    """Upsert one MusicFile from local tags/path. Returns (row, created)."""
    path = Path(file_path).resolve()
    root_path = Path(root or config.paths.library).resolve()
    existing = db.query(MusicFile).filter(MusicFile.file_path == str(path)).first()
    created = False
    if not existing:
        existing = MusicFile(file_path=str(path))
        db.add(existing)
        created = True

    tags = read_existing_tags(str(path))
    path_hint = _infer_from_path(path, root_path)
    audio_meta = read_audio_metadata(str(path))

    title = tags.get("title") or path_hint.get("title") or path.stem
    track_from_name, cleaned_title = _clean_track_title(title)
    if not tags.get("title") and cleaned_title:
        title = cleaned_title

    existing.link_path = str(path)
    existing.format = path.suffix.lstrip(".")
    existing.title = title
    existing.artist = tags.get("artist") or tags.get("album_artist") or path_hint.get("artist") or existing.artist
    existing.album_artist = tags.get("album_artist") or path_hint.get("artist") or existing.album_artist or existing.artist
    existing.album = tags.get("album") or path_hint.get("album") or existing.album
    existing.year = tags.get("year") or existing.year
    existing.genre = tags.get("genre") or existing.genre
    existing.track_number = tags.get("track_number") or track_from_name or existing.track_number
    existing.disc_number = tags.get("disc_number") or existing.disc_number
    existing.duration = audio_meta.get("duration")
    existing.bitrate = audio_meta.get("bitrate")
    existing.sample_rate = audio_meta.get("sample_rate")
    existing.channels = audio_meta.get("channels")
    # Treat local import as scraped when it has usable musical identity from tag/path.
    existing.scraped = bool(existing.title and (existing.artist or existing.album))

    # Probe local assets so future health checks get a chance to see sidecars created by scan.
    # We don't persist cover/lyrics flags in the current flat model, but this validates readable assets.
    _ = read_sidecar_lyrics(str(path)) or tags.get("lyrics")
    _ = find_local_cover_data(path.parent) or (read_embedded_cover(str(path)) if tags.get("has_artwork") else None)
    return existing, created


def _is_unknown_artist(artist: str | None) -> bool:
    if not artist:
        return True
    return artist.strip().lower() in {"", "unknown artist", "未知艺人", "unknown", "various artists"}


def _has_lrc(path: str | Path) -> bool:
    try:
        return Path(path).with_suffix(".lrc").exists()
    except Exception:
        return False


def _has_cover(path: str | Path) -> bool:
    p = Path(path)
    return bool(find_local_cover_data(p.parent) or read_embedded_cover(str(p)))


def _cue_split_candidates(root: Path) -> int:
    count = 0
    for path in iter_audio_files(root):
        same = path.with_suffix(".cue")
        if same.exists():
            count += 1
            continue
        try:
            cues = list(path.parent.glob("*.cue"))
            if len(cues) == 1:
                count += 1
        except Exception:
            continue
    return count


def _health_summary(db: Session, root_path: Path) -> dict:
    rows = db.query(MusicFile).all()
    summary = {
        "missing_cover": 0,
        "missing_lyrics": 0,
        "missing_duration": 0,
        "unknown_artist": 0,
        "unscraped": 0,
        "cue_candidates": _cue_split_candidates(root_path),
        "missing_files": 0,
    }
    for row in rows:
        if row.file_path and not Path(row.file_path).exists():
            summary["missing_files"] += 1
        if not row.file_path:
            continue
        if not _has_cover(row.file_path):
            summary["missing_cover"] += 1
        if not _has_lrc(row.file_path):
            summary["missing_lyrics"] += 1
        if not row.duration or row.duration <= 0:
            summary["missing_duration"] += 1
        if _is_unknown_artist(row.artist):
            summary["unknown_artist"] += 1
        if not row.scraped:
            summary["unscraped"] += 1
    return summary


def scan_library(db: Session, root: str | Path | None = None, remove_missing: bool = False, progress=None) -> dict:
    """Scan root and upsert MusicFile records."""
    root_path = Path(root or config.paths.library).resolve()
    files = list(iter_audio_files(root_path))
    seen = {str(p.resolve()) for p in files}
    created = updated = errors = 0
    for idx, path in enumerate(files):
        try:
            _row, was_created = upsert_file_from_local(db, path, root_path)
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
            if progress:
                progress(idx + 1, len(files), path.name)
        except Exception as exc:
            errors += 1
            logger.warning("library scan failed for %s: %s", path, exc)
    removed = 0
    if remove_missing:
        rows = db.query(MusicFile).all()
        for row in rows:
            if row.file_path and str(Path(row.file_path).resolve()).startswith(str(root_path)) and row.file_path not in seen:
                db.delete(row)
                removed += 1
    db.commit()
    health = _health_summary(db, root_path)
    return {"root": str(root_path), "total": len(files), "created": created, "updated": updated, "removed": removed, "errors": errors, "health": health}
