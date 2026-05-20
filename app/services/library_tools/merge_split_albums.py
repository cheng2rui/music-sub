"""Merge historical same-album folders split by different track artists."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import config
from app.models import MusicFile
from app.organizer.naming import build_library_path
from app.scrapers.tagger import _move_sidecars, copy_or_move_album_sidecars
from app.services.album_identity import canonical_album_artist, norm_text, primary_artist
from app.services.library_audit import log_library_event
from app.services.library_tools.base import PreviewItem, ToolPreview


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    idx = 1
    while True:
        candidate = path.with_name(f"{stem} ({idx}){suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def _album_key(f: MusicFile) -> str:
    return norm_text(f.album or "") or f"__unknown_album__:{f.id}"


def _target_artist(db: Session, rows: list[MusicFile], options: dict[str, Any]) -> str:
    forced = str(options.get("album_artist") or "").strip()
    if forced:
        return primary_artist(forced) or forced
    first = sorted(rows, key=lambda r: (r.track_number is None, r.track_number or 9999, r.id))[0]
    return canonical_album_artist(db, first.album, first.album_artist or first.artist, current_id=first.id) or primary_artist(first.album_artist or first.artist) or "Unknown Artist"


def _target_path(db: Session, f: MusicFile, rows: list[MusicFile], options: dict[str, Any]) -> Path | None:
    if not f.file_path:
        return None
    artist = _target_artist(db, rows, options)
    album = f.album or Path(f.file_path).parent.name or "Unknown Album"
    root = Path(options.get("library_root") or config.paths.library)
    rel_dir = build_library_path(artist, album, config.paths.structure)
    return _unique_path((root / rel_dir / Path(f.file_path).name).resolve())


def _group_rows(files: list[MusicFile]) -> list[list[MusicFile]]:
    groups: dict[str, list[MusicFile]] = {}
    for f in files:
        groups.setdefault(_album_key(f), []).append(f)
    return [rows for rows in groups.values() if rows]


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    items: list[PreviewItem] = []
    changed = 0
    for rows in _group_rows(files):
        target_artist = _target_artist(db, rows, options)
        for f in rows:
            target = _target_path(db, f, rows, options)
            same = bool(target and f.file_path and target == Path(f.file_path).resolve() and (f.album_artist or "") == target_artist)
            if target and not same:
                changed += 1
            items.append(PreviewItem(
                file_id=f.id,
                file_path=f.file_path,
                label=Path(f.file_path).name if f.file_path else f.title or str(f.id),
                before={"file_path": f.file_path, "album_artist": f.album_artist, "artist": f.artist, "album": f.album},
                after={"file_path": str(target) if target else "", "album_artist": target_artist},
                would_change=bool(target and not same),
                reason="合并到主歌手专辑文件夹" if target and not same else "",
            ))
    return ToolPreview(tool="merge_split_albums", items=items, summary={"changed": changed, "total": len(items)})


def _remove_empty_parents(start: Path, stop: Path) -> int:
    removed = 0
    current = start
    stop = stop.resolve()
    while True:
        try:
            current_resolved = current.resolve()
            current_resolved.relative_to(stop)
        except Exception:
            break
        if current_resolved == stop:
            break
        try:
            if current.exists() and not any(current.iterdir()):
                current.rmdir()
                removed += 1
                current = current.parent
                continue
        except Exception:
            pass
        break
    return removed


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    moved = 0
    updated = 0
    skipped = 0
    failed = 0
    sidecars_total = 0
    removed_dirs = 0
    root = Path(options.get("library_root") or config.paths.library).resolve()
    for rows in _group_rows(files):
        target_artist = _target_artist(db, rows, options)
        for idx, f in enumerate(rows):
            try:
                if not f.file_path:
                    skipped += 1
                    on_progress(idx, "skip:no path")
                    continue
                source = Path(f.file_path).resolve()
                target = _target_path(db, f, rows, options)
                if not target:
                    skipped += 1
                    on_progress(idx, "skip:no target")
                    continue
                old_parent = source.parent
                changed_path = source.exists() and source != target
                if changed_path:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(target))
                    sidecars = _move_sidecars(source, target, copy=False)
                    album_sidecars = copy_or_move_album_sidecars(old_parent, target.parent, copy=False)
                    sidecars_total += len(sidecars) + album_sidecars
                    removed_dirs += _remove_empty_parents(old_parent, root)
                    f.file_path = str(target)
                    f.link_path = str(target)
                    moved += 1
                    log_library_event(
                        db=db,
                        action="move",
                        file_path=str(source),
                        restore_path=str(target),
                        message="合并同名专辑分裂文件夹",
                        details={"file_id": f.id, "album": f.album, "album_artist": target_artist},
                    )
                if f.album_artist != target_artist:
                    f.album_artist = target_artist
                    updated += 1
                on_progress(idx, f"-> {target_artist}/{f.album or target.parent.name}/{target.name}")
            except Exception as exc:
                failed += 1
                on_progress(idx, f"err:{exc}")
    return {"moved": moved, "updated_album_artist": updated, "skipped": skipped, "failed": failed, "sidecars": sidecars_total, "removed_dirs": removed_dirs, "total": len(files)}
