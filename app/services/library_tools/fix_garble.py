"""Garble repair tool for music metadata that survived a wrong decode.

Common patterns we try to fix:
- GBK bytes mis-decoded as latin-1 (very common for legacy ID3v1 tags)
- UTF-8 bytes mis-decoded as latin-1
- ID3 frames stored as cp1252 / cp949 fragments
"""
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


_DEFAULT_FIELDS = ("title", "artist", "album", "genre")
_TARGET_ENCODINGS = ("utf-8", "gbk", "gb18030", "big5")
_SOURCE_ENCODINGS = ("latin-1", "cp1252")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_LIKELY_BAD_RE = re.compile(r"[\u00a0-\u00ff]{2,}")


def _looks_garbled(text: str) -> bool:
    if not text:
        return False
    bad = _LIKELY_BAD_RE.search(text)
    return bool(bad) and not _CJK_RE.search(text)


def _score(text: str) -> int:
    """Higher is more likely a clean Chinese/Japanese/Korean string."""
    if not text:
        return -1
    cjk = len(_CJK_RE.findall(text))
    weird = len(_LIKELY_BAD_RE.findall(text))
    replacement = text.count("\ufffd")
    return cjk * 5 - weird * 4 - replacement * 8


def _candidate_fixes(text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for src in _SOURCE_ENCODINGS:
        try:
            raw = text.encode(src, errors="strict")
        except UnicodeEncodeError:
            continue
        for tgt in _TARGET_ENCODINGS:
            try:
                fixed = raw.decode(tgt, errors="strict")
            except (UnicodeDecodeError, LookupError):
                continue
            if fixed and fixed != text:
                candidates.append((f"{src}->{tgt}", fixed))
    return candidates


def _best_candidate(text: str) -> tuple[str, str] | None:
    base = _score(text)
    best: tuple[str, str] | None = None
    best_score = base
    for label, candidate in _candidate_fixes(text):
        candidate_score = _score(candidate)
        if candidate_score > best_score and _CJK_RE.search(candidate):
            best = (label, candidate)
            best_score = candidate_score
    return best


def _propose(f: MusicFile, fields: tuple[str, ...]) -> dict[str, tuple[str, str]]:
    """Return ``{field: (label, fixed)}`` for fields that look garbled."""
    out: dict[str, tuple[str, str]] = {}
    for key in fields:
        value = getattr(f, key, None)
        if not isinstance(value, str) or not value:
            continue
        if not _looks_garbled(value):
            continue
        candidate = _best_candidate(value)
        if not candidate:
            continue
        out[key] = candidate
    return out


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    fields = tuple(options.get("fields") or _DEFAULT_FIELDS)
    items: list[PreviewItem] = []
    changed = 0
    for f in files:
        proposals = _propose(f, fields)
        before = {key: getattr(f, key, None) for key in fields}
        after = {**before}
        reason_parts: list[str] = []
        for key, (label, fixed) in proposals.items():
            after[key] = fixed
            reason_parts.append(f"{key}: ({label}) {before[key]!r}\u2192{fixed!r}")
        items.append(PreviewItem(
            file_id=f.id,
            file_path=f.file_path,
            label=Path(f.file_path).name if f.file_path else f.title or str(f.id),
            before=before,
            after=after,
            would_change=bool(proposals),
            reason=" | ".join(reason_parts),
        ))
        if proposals:
            changed += 1
    return ToolPreview(tool="fix_garble", items=items, summary={"changed": changed, "total": len(items)})


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    fields = tuple(options.get("fields") or _DEFAULT_FIELDS)
    write_tags = bool(options.get("write_tags", False))
    updated = 0
    for idx, f in enumerate(files):
        try:
            proposals = _propose(f, fields)
            if not proposals:
                on_progress(idx, "no change")
                continue
            for key, (_label, fixed) in proposals.items():
                setattr(f, key, fixed)
            if write_tags and f.file_path and os.path.exists(f.file_path):
                try:
                    import music_tag
                    audio = music_tag.load_file(f.file_path)
                    for key in proposals:
                        audio[key] = getattr(f, key)
                    audio.save()
                except Exception as exc:
                    on_progress(idx, f"err:tag write failed: {exc}")
                    continue
            updated += 1
            on_progress(idx, ", ".join(proposals.keys()))
        except Exception as exc:
            on_progress(idx, f"err:{exc}")
    return {"updated": updated, "total": len(files), "fields": list(fields)}
