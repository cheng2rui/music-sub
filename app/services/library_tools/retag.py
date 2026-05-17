"""Retag tool: rewrite title/artist/album/year/genre via templates or values."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview

logger = logging.getLogger(__name__)


_TEMPLATE_RE = re.compile(r"\$\{(?P<name>\w+)\}")


SUPPORTED_FIELDS = ("title", "artist", "album", "year", "genre", "track_number", "disc_number")


def _file_vars(f: MusicFile) -> dict[str, Any]:
    stem = Path(f.file_path).stem if f.file_path else ""
    return {
        "title": f.title or "",
        "artist": f.artist or "",
        "album": f.album or "",
        "year": f.year or "",
        "genre": f.genre or "",
        "track_number": f.track_number or "",
        "disc_number": f.disc_number or "",
        "filename": stem,
    }


def _resolve_template(value: Any, vars_dict: dict[str, Any]) -> Any:
    if not isinstance(value, str) or "${" not in value:
        return value
    return _TEMPLATE_RE.sub(lambda m: str(vars_dict.get(m.group("name"), "")), value)


def _apply_options(f: MusicFile, options: dict[str, Any]) -> dict[str, Any]:
    vars_dict = _file_vars(f)
    after = vars_dict.copy()
    fields = options.get("fields") or {}
    for key, raw in fields.items():
        if key not in SUPPORTED_FIELDS:
            continue
        if raw is None or raw == "":
            continue
        resolved = _resolve_template(raw, vars_dict)
        after[key] = resolved
    return after


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    items: list[PreviewItem] = []
    changed = 0
    for f in files:
        before = _file_vars(f)
        after = _apply_options(f, options)
        diff = {k: after[k] for k in SUPPORTED_FIELDS if str(before.get(k, "")) != str(after.get(k, ""))}
        items.append(PreviewItem(
            file_id=f.id,
            file_path=f.file_path,
            label=before.get("filename", "") or str(f.id),
            before={k: before.get(k) for k in SUPPORTED_FIELDS},
            after={k: after.get(k) for k in SUPPORTED_FIELDS},
            would_change=bool(diff),
            reason=", ".join(f"{k}={v!r}" for k, v in diff.items()) if diff else "",
        ))
        if diff:
            changed += 1
    return ToolPreview(tool="retag", items=items, summary={"changed": changed, "total": len(items)})


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    updated = 0
    for idx, f in enumerate(files):
        try:
            after = _apply_options(f, options)
            changed_fields: list[str] = []
            for key in SUPPORTED_FIELDS:
                value = after.get(key)
                if value is None or value == "":
                    continue
                # year/track_number/disc_number be coerced to int when possible
                coerced: Any = value
                if key in {"year", "track_number", "disc_number"}:
                    try:
                        coerced = int(str(value).strip())
                    except (ValueError, AttributeError):
                        coerced = None
                current = getattr(f, key)
                if coerced != current:
                    setattr(f, key, coerced)
                    changed_fields.append(key)
            if changed_fields:
                updated += 1
                if f.file_path and os.path.exists(f.file_path):
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
