"""Split meta tool: pull artist / extra info out of messy title strings."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview


# Default patterns; users can override via options["patterns"].
_DEFAULT_PATTERNS = [
    # "Artist - Title"
    r"^(?P<artist>[^-]+?)\s+-\s+(?P<title>.+?)\s*$",
    # "Title - Artist" (when artist hint suggests so)
    r"^(?P<title>.+?)\s+-\s+(?P<artist>[^-]+?)\s*$",
    # "Title (Live|Remix|Cover|Acoustic|...)"
    r"^(?P<title>.+?)\s*\((?P<extra>Live|Remix|Cover|Acoustic|Demo|Karaoke|Instrumental)\)\s*$",
    # "Title 【Live】"
    r"^(?P<title>.+?)\s*[【\[](?P<extra>Live|Remix|Cover|Acoustic|Demo|Karaoke|Instrumental)[】\]]\s*$",
]


def _build_patterns(options: dict[str, Any]) -> list[re.Pattern[str]]:
    raw = options.get("patterns") or _DEFAULT_PATTERNS
    return [re.compile(p, re.IGNORECASE) for p in raw]


def _propose(f: MusicFile, patterns: list[re.Pattern[str]],
             prefer_artist_left: bool) -> dict[str, Any]:
    title = (f.title or "").strip()
    if not title:
        return {}
    for pattern in patterns:
        m = pattern.match(title)
        if not m:
            continue
        groups = {k: v.strip() for k, v in m.groupdict().items() if v}
        if not groups:
            continue
        # 当模板里同时给出 artist+title，按 prefer_artist_left 决定方向。
        if "artist" in groups and "title" in groups:
            if prefer_artist_left:
                pass
            else:
                groups["artist"], groups["title"] = groups["title"], groups["artist"]
        return groups
    return {}


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    patterns = _build_patterns(options)
    prefer_artist_left = options.get("prefer_artist_left", True)
    items: list[PreviewItem] = []
    changed = 0
    for f in files:
        proposal = _propose(f, patterns, prefer_artist_left)
        before = {"title": f.title, "artist": f.artist, "extra": ""}
        after = before | proposal
        diff = {k: after[k] for k in ("title", "artist", "extra") if str(before.get(k, "")) != str(after.get(k, ""))}
        items.append(PreviewItem(
            file_id=f.id,
            file_path=f.file_path,
            label=Path(f.file_path).name if f.file_path else f.title or str(f.id),
            before=before,
            after=after,
            would_change=bool(diff),
            reason=", ".join(f"{k}={v!r}" for k, v in diff.items()) if diff else "",
        ))
        if diff:
            changed += 1
    return ToolPreview(tool="split_meta", items=items, summary={"changed": changed, "total": len(items)})


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    patterns = _build_patterns(options)
    prefer_artist_left = options.get("prefer_artist_left", True)
    write_tags = bool(options.get("write_tags", False))
    updated = 0
    for idx, f in enumerate(files):
        try:
            proposal = _propose(f, patterns, prefer_artist_left)
            if not proposal:
                on_progress(idx, "no match")
                continue
            changed_fields = []
            if proposal.get("title") and proposal["title"] != f.title:
                f.title = proposal["title"]
                changed_fields.append("title")
            if proposal.get("artist") and proposal["artist"] != f.artist:
                f.artist = proposal["artist"]
                changed_fields.append("artist")
            extra = proposal.get("extra")
            if extra:
                f.genre = (f.genre or "").strip()
                if extra.lower() not in (f.genre or "").lower():
                    f.genre = (f.genre + ", " if f.genre else "") + extra
                    changed_fields.append("genre")
            if changed_fields:
                updated += 1
                if write_tags and f.file_path and os.path.exists(f.file_path):
                    try:
                        import music_tag
                        audio = music_tag.load_file(f.file_path)
                        for key in changed_fields:
                            audio[key] = getattr(f, key)
                        audio.save()
                    except Exception as exc:
                        on_progress(idx, f"err:tag write failed: {exc}")
                        continue
            on_progress(idx, ", ".join(changed_fields) or "no change")
        except Exception as exc:
            on_progress(idx, f"err:{exc}")
    return {"updated": updated, "total": len(files)}
