"""Simplified <-> Traditional Chinese converter for library metadata.

Uses ``opencc-python-reimplemented`` (pure Python). Falls back to a noop
converter when the dependency is missing so previews still work.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview

logger = logging.getLogger(__name__)


_DEFAULT_FIELDS = ("title", "artist", "album", "genre")


def _build_converter(target: str) -> Callable[[str], str]:
    profile = "t2s" if target == "s" else "s2t"
    try:
        from opencc import OpenCC
        cc = OpenCC(profile)
        return cc.convert
    except Exception as exc:  # pragma: no cover - dep absence path
        logger.warning("opencc unavailable, falling back to identity (%s): %s", profile, exc)
        return lambda text: text


def _changes(f: MusicFile, fields: tuple[str, ...], converter: Callable[[str], str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in fields:
        value = getattr(f, key, None)
        if not isinstance(value, str) or not value:
            continue
        new = converter(value)
        if new and new != value:
            out[key] = new
    return out


def _preview_factory(target: str):
    def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
        fields = tuple(options.get("fields") or _DEFAULT_FIELDS)
        converter = _build_converter(target)
        items: list[PreviewItem] = []
        changed = 0
        for f in files:
            diff = _changes(f, fields, converter)
            before = {key: getattr(f, key, None) for key in fields}
            after = {**before, **diff}
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
        tool_id = "zh_t2s" if target == "s" else "zh_s2t"
        return ToolPreview(tool=tool_id,
                           items=items,
                           summary={"changed": changed, "total": len(items), "target": target})
    return preview


def _apply_factory(target: str):
    def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
        fields = tuple(options.get("fields") or _DEFAULT_FIELDS)
        write_tags = bool(options.get("write_tags", False))
        converter = _build_converter(target)
        updated = 0
        for idx, f in enumerate(files):
            try:
                diff = _changes(f, fields, converter)
                if not diff:
                    on_progress(idx, "no change")
                    continue
                for key, value in diff.items():
                    setattr(f, key, value)
                if write_tags and f.file_path and os.path.exists(f.file_path):
                    try:
                        import music_tag
                        audio = music_tag.load_file(f.file_path)
                        for key in diff:
                            audio[key] = getattr(f, key)
                        audio.save()
                    except Exception as exc:
                        on_progress(idx, f"err:tag write failed: {exc}")
                        continue
                updated += 1
                on_progress(idx, ", ".join(diff.keys()))
            except Exception as exc:
                on_progress(idx, f"err:{exc}")
        return {"updated": updated, "total": len(files), "fields": list(fields), "target": target}
    return apply


# Public hooks: target = 's' (-> simplified) / 't' (-> traditional)
preview_to_simplified = _preview_factory("s")
apply_to_simplified = _apply_factory("s")
preview_to_traditional = _preview_factory("t")
apply_to_traditional = _apply_factory("t")
