"""Identify tool: infer artist/album/title/track from path + filename."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import config
from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview


# 01. Title  /  01 Title  /  01 - Title
_LEAD_TRACK_RE = re.compile(r"^\s*(?P<track>\d{1,2})\s*[\.\-_)\s]+\s*(?P<title>.+?)\s*$")
# Title - Artist  or  Artist - Title
_DASH_RE = re.compile(r"^\s*(?P<a>.+?)\s+-\s+(?P<b>.+?)\s*$")


def _infer_from_library(file_path: str) -> tuple[str, str]:
    try:
        rel = Path(file_path).resolve().relative_to(Path(config.paths.library).resolve())
    except Exception:
        return "", ""
    parts = rel.parts
    if len(parts) < 3 or parts[0] == parts[1]:
        return "", ""
    return parts[0], parts[1]


def _infer_from_filename(stem: str, hint_artist: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    text = stem.strip()
    m = _LEAD_TRACK_RE.match(text)
    if m:
        out["track_number"] = m.group("track")
        text = m.group("title").strip()
    if " - " in text:
        m = _DASH_RE.match(text)
        if m:
            a, b = m.group("a").strip(), m.group("b").strip()
            # 优先按 hint_artist 决定哪边是 artist
            if hint_artist and hint_artist == a:
                out["title"] = b
            elif hint_artist and hint_artist == b:
                out["title"] = a
            else:
                # 默认认为「左 - 右」是 artist - title
                out["artist"] = a
                out["title"] = b
            return out
    if text:
        out["title"] = text
    return out


def _infer(file: MusicFile) -> dict[str, Any]:
    path_artist, path_album = _infer_from_library(file.file_path or "")
    stem = Path(file.file_path or "").stem
    parts = _infer_from_filename(stem, hint_artist=path_artist)
    inferred_artist = path_artist or parts.get("artist") or file.artist or ""
    after = {
        "artist": inferred_artist,
        "album_artist": path_artist or file.album_artist or inferred_artist,
        "album": path_album or file.album or "",
        "title": parts.get("title") or file.title or stem,
        "track_number": int(parts["track_number"]) if parts.get("track_number") else file.track_number,
    }
    return after


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    items: list[PreviewItem] = []
    changed = 0
    for f in files:
        before = {
            "artist": f.artist,
            "album_artist": f.album_artist,
            "album": f.album,
            "title": f.title,
            "track_number": f.track_number,
        }
        after = _infer(f)
        diff = {k: v for k, v in after.items() if v not in (None, "") and before.get(k) != v}
        items.append(PreviewItem(
            file_id=f.id,
            file_path=f.file_path,
            label=Path(f.file_path).name if f.file_path else f.title or str(f.id),
            before=before,
            after=after,
            would_change=bool(diff),
            reason=", ".join(f"{k}: {before.get(k)!r}\u2192{after[k]!r}" for k in diff) if diff else "",
        ))
        if diff:
            changed += 1
    return ToolPreview(tool="identify", items=items, summary={"changed": changed, "total": len(items)})


def apply(db: Session, files: list[MusicFile], options: dict[str, Any],
          on_progress) -> dict:
    write_tags = bool(options.get("write_tags", False))
    updated = 0
    for idx, f in enumerate(files):
        try:
            after = _infer(f)
            changed_fields = []
            for key in ("artist", "album_artist", "album", "title", "track_number"):
                value = after.get(key)
                if value in (None, ""):
                    continue
                if getattr(f, key) != value:
                    setattr(f, key, value)
                    changed_fields.append(key)
            if changed_fields:
                updated += 1
            if write_tags and changed_fields and f.file_path and os.path.exists(f.file_path):
                try:
                    import music_tag
                    audio = music_tag.load_file(f.file_path)
                    tag_keys = {"album_artist": "albumartist", "track_number": "tracknumber"}
                    for key in changed_fields:
                        audio[tag_keys.get(key, key)] = getattr(f, key)
                    audio.save()
                except Exception as exc:
                    on_progress(idx, f"err:tag write failed: {exc}")
                    continue
            on_progress(idx, ", ".join(changed_fields) or "no change")
        except Exception as exc:
            on_progress(idx, f"err:{exc}")
    return {"updated": updated, "total": len(files), "write_tags": write_tags}
