"""Organize tool: rename / move files into a canonical {artist}/{album}/track layout."""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import config
from app.models import MusicFile
from app.scrapers.tagger import _move_sidecars, copy_or_move_album_sidecars
from app.services.library_tools.base import PreviewItem, ToolPreview

logger = logging.getLogger(__name__)


_DEFAULT_TEMPLATE = "{artist}/{album}/{disc:02d}-{track:02d} {title}{ext}"
_INVALID = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def _safe(text: str) -> str:
    cleaned = _INVALID.sub("_", (text or "").strip())
    cleaned = cleaned.rstrip(". ")
    return cleaned or "Unknown"


def _vars_for(f: MusicFile) -> dict[str, Any]:
    ext = Path(f.file_path).suffix if f.file_path else ""
    return {
        "artist": _safe(f.album_artist or f.artist or "Unknown Artist"),
        "album": _safe(f.album or "Unknown Album"),
        "title": _safe(f.title or Path(f.file_path).stem if f.file_path else str(f.id)),
        "track": int(f.track_number or 0),
        "disc": int(f.disc_number or 1),
        "year": int(f.year or 0),
        "ext": ext,
    }


def _format(template: str, vars_dict: dict[str, Any]) -> str:
    try:
        return template.format(**vars_dict)
    except (KeyError, ValueError, IndexError):
        return template


def _target_path(f: MusicFile, options: dict[str, Any]) -> Path | None:
    if not f.file_path:
        return None
    template = options.get("template") or _DEFAULT_TEMPLATE
    library_root = Path(options.get("library_root") or config.paths.library)
    rel = _format(template, _vars_for(f)).lstrip("/")
    return (library_root / rel).resolve()


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    items: list[PreviewItem] = []
    changed = 0
    for f in files:
        target = _target_path(f, options)
        before = {"file_path": f.file_path}
        after = {"file_path": str(target) if target else ""}
        same = bool(target) and target == Path(f.file_path or "").resolve()
        items.append(PreviewItem(
            file_id=f.id,
            file_path=f.file_path,
            label=Path(f.file_path).name if f.file_path else str(f.id),
            before=before,
            after=after,
            would_change=bool(target) and not same,
            reason="" if same else (f"-> {after['file_path']}" if target else "no path"),
        ))
        if target and not same:
            changed += 1
    return ToolPreview(tool="organize", items=items, summary={"changed": changed, "total": len(items)})


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    keep_original = bool(options.get("keep_original", False))
    moved = 0
    for idx, f in enumerate(files):
        try:
            target = _target_path(f, options)
            if not target or not f.file_path:
                on_progress(idx, "skip")
                continue
            source = Path(f.file_path)
            if not source.exists():
                on_progress(idx, f"err:missing source {source}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target == source.resolve():
                on_progress(idx, "already in place")
                continue
            if target.exists():
                on_progress(idx, f"err:target exists {target}")
                continue
            try:
                if keep_original:
                    shutil.copy2(source, target)
                else:
                    shutil.move(str(source), str(target))
                sidecars = _move_sidecars(source, target, copy=keep_original)
                album_sidecars = copy_or_move_album_sidecars(source.parent, target.parent, copy=keep_original)
            except Exception as exc:
                on_progress(idx, f"err:move failed: {exc}")
                continue
            f.file_path = str(target)
            f.link_path = str(target)
            moved += 1
            sidecar_count = len(sidecars) + album_sidecars
            suffix = f" (+{sidecar_count} sidecars)" if sidecar_count else ""
            on_progress(idx, f"-> {target.name}{suffix}")
        except Exception as exc:
            on_progress(idx, f"err:{exc}")
    return {"moved": moved, "total": len(files)}
