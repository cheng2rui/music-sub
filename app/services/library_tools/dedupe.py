"""Dedupe tool: detect duplicate tracks and suggest one to keep per group."""
from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview


_NORMALIZE_RE = re.compile(r"[\s\-_·•·,，。.：:;;'\"“”‘’()（）\[\]【】{}<>《》]+")


def _normalize(text: str | None) -> str:
    return _NORMALIZE_RE.sub("", (text or "").lower())


def _signature(f: MusicFile) -> str:
    duration_bucket = int(round((f.duration or 0) / 2)) if f.duration else 0
    return f"{_normalize(f.artist)}|{_normalize(f.title)}|{duration_bucket}"


def _score_keep(f: MusicFile) -> tuple[int, int, int]:
    """Pick one to keep: prefer higher bitrate, longer duration, larger file."""
    try:
        size = os.path.getsize(f.file_path) if f.file_path and os.path.exists(f.file_path) else 0
    except OSError:
        size = 0
    return (int(f.bitrate or 0), int(f.duration or 0), size)


def _build_groups(files: list[MusicFile]) -> dict[str, list[MusicFile]]:
    buckets: dict[str, list[MusicFile]] = defaultdict(list)
    for f in files:
        if not (f.title or "").strip():
            continue
        buckets[_signature(f)].append(f)
    return {k: v for k, v in buckets.items() if len(v) > 1}


def _format_meta(f: MusicFile) -> dict[str, Any]:
    return {
        "title": f.title,
        "artist": f.artist,
        "album": f.album,
        "duration": f.duration,
        "bitrate": f.bitrate,
        "format": f.format,
        "file_path": f.file_path,
    }


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    groups = _build_groups(files)
    items: list[PreviewItem] = []
    duplicates = 0
    for sig, group in groups.items():
        keeper = max(group, key=_score_keep)
        for f in group:
            items.append(PreviewItem(
                file_id=f.id,
                file_path=f.file_path,
                label=Path(f.file_path).name if f.file_path else str(f.id),
                before=_format_meta(f),
                after={"action": "keep" if f.id == keeper.id else "duplicate", "group": sig},
                would_change=f.id != keeper.id,
                reason="\u4fdd\u7559" if f.id == keeper.id else f"\u91cd\u590d\u4e8e #{keeper.id}",
            ))
            if f.id != keeper.id:
                duplicates += 1
    summary = {"groups": len(groups), "duplicates": duplicates, "total": len(items)}
    return ToolPreview(tool="dedupe", items=items, summary=summary)


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    """Apply mode acts only on file ids the caller marked for removal.

    The frontend should display the preview, let the user pick which
    duplicates to delete, then send those ids back as ``options["delete_ids"]``.
    Apply ignores any id that isn't in that list, even when it shows up in
    ``files``. Files are moved into ``trash_dir`` instead of being unlinked
    when ``options["mode"] == "trash"``.
    """
    delete_ids = set(int(i) for i in options.get("delete_ids", []) if i is not None)
    if not delete_ids:
        return {"deleted": 0, "trashed": 0, "total": len(files), "warning": "no delete_ids supplied"}
    mode = options.get("mode", "trash")  # trash | delete
    trash_dir = Path(options.get("trash_dir") or "data/.trash/dedupe")
    deleted = trashed = 0
    for idx, f in enumerate(files):
        if f.id not in delete_ids:
            on_progress(idx, "skip")
            continue
        try:
            if not f.file_path or not os.path.exists(f.file_path):
                # Even if missing on disk, drop the DB row so the duplicate disappears.
                db.delete(f)
                on_progress(idx, "db row removed (file missing)")
                deleted += 1
                continue
            if mode == "delete":
                os.remove(f.file_path)
                deleted += 1
                action = "deleted"
            else:
                trash_dir.mkdir(parents=True, exist_ok=True)
                target = trash_dir / Path(f.file_path).name
                if target.exists():
                    target = trash_dir / f"{f.id}_{Path(f.file_path).name}"
                Path(f.file_path).rename(target)
                trashed += 1
                action = f"trashed -> {target}"
            db.delete(f)
            on_progress(idx, action)
        except Exception as exc:
            on_progress(idx, f"err:{exc}")
    return {"deleted": deleted, "trashed": trashed, "total": len(delete_ids), "mode": mode}
