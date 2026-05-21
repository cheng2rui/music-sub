"""CUE split candidate tool.

Find existing MusicFile rows whose audio file has a matching .cue and delegate
preview/apply to the split_audio tool on just those files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview
from app.services.library_tools import split_audio
from app.services.library_health_rules import cue_split_candidate


def _has_cue(file: MusicFile) -> bool:
    return cue_split_candidate(file.file_path, duration=file.duration)


def _candidates(files: list[MusicFile]) -> list[MusicFile]:
    return [f for f in files if _has_cue(f)]


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    cands = _candidates(files)
    if not cands:
        return ToolPreview(tool="cue_candidates", summary={"empty": True, "total": len(files)})
    return split_audio.preview(db, cands, options)


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    cands = _candidates(files)
    if not cands:
        return {"split": 0, "total": len(files), "candidates": 0}
    summary = split_audio.apply(db, cands, options, on_progress)
    summary["candidates"] = len(cands)
    return summary
