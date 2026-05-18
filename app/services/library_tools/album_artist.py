"""Album artist repair tool.

Repairs MusicFile.album_artist without changing per-track artist/title. This is
useful after introducing album_artist grouping: old libraries may have albums
split by track artist because album_artist was missing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import config
from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview


def _infer_path_artist(file_path: str | None) -> str:
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


def _target_album_artist(file: MusicFile, options: dict[str, Any]) -> str:
    forced = str(options.get("album_artist") or "").strip()
    if forced:
        return forced
    path_artist = _infer_path_artist(file.file_path)
    if path_artist:
        return path_artist
    return file.album_artist or file.artist or ""


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    items: list[PreviewItem] = []
    changed = 0
    for f in files:
        target = _target_album_artist(f, options)
        before = {"artist": f.artist, "album_artist": f.album_artist, "album": f.album}
        after = {"album_artist": target}
        would_change = bool(target and f.album_artist != target)
        if would_change:
            changed += 1
        items.append(PreviewItem(
            file_id=f.id,
            file_path=f.file_path,
            label=Path(f.file_path).name if f.file_path else f.title or str(f.id),
            before=before,
            after=after,
            would_change=would_change,
            reason=f"album_artist: {f.album_artist!r}→{target!r}" if would_change else "",
        ))
    return ToolPreview(tool="album_artist", items=items, summary={"changed": changed, "total": len(items)})


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    write_tags = bool(options.get("write_tags", False))
    updated = 0
    for idx, f in enumerate(files):
        target = _target_album_artist(f, options)
        if not target or f.album_artist == target:
            on_progress(idx, "no change")
            continue
        try:
            f.album_artist = target
            updated += 1
            if write_tags and f.file_path and Path(f.file_path).exists():
                try:
                    import music_tag
                    audio = music_tag.load_file(f.file_path)
                    audio["albumartist"] = target
                    audio.save()
                except Exception as exc:
                    on_progress(idx, f"err:tag write failed: {exc}")
                    continue
            on_progress(idx, f"album_artist={target}")
        except Exception as exc:
            on_progress(idx, f"err:{exc}")
    return {"updated": updated, "total": len(files), "write_tags": write_tags}
