"""Common types and helpers for library tools."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import MusicFile


class ToolError(RuntimeError):
    """Raised when a tool encounters an unrecoverable error."""


@dataclass
class PreviewItem:
    file_id: int
    file_path: str
    label: str
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    would_change: bool = True
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "file_path": self.file_path,
            "label": self.label,
            "before": self.before,
            "after": self.after,
            "would_change": self.would_change,
            "reason": self.reason,
        }


@dataclass
class ToolPreview:
    tool: str
    items: list[PreviewItem] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------


def resolve_files(db: Session, *, file_ids: Optional[list[int]] = None,
                  album_artist: Optional[str] = None,
                  album_name: Optional[str] = None,
                  limit: int = 500) -> list[MusicFile]:
    """Fetch the music files targeted by a tool invocation.

    Selection precedence: explicit ``file_ids`` > ``album_artist + album_name``.
    A bare query (no ids, no album) returns at most ``limit`` recent files so a
    misconfigured request doesn't accidentally walk the whole library.
    """
    if file_ids:
        return db.query(MusicFile).filter(MusicFile.id.in_(file_ids)).all()

    query = db.query(MusicFile)
    if album_artist:
        artist_group = func.coalesce(func.nullif(MusicFile.album_artist, ""), func.nullif(MusicFile.artist, ""), "Unknown Artist")
        artist_filter = (artist_group == album_artist)
        query = query.filter(artist_filter)
    if album_name:
        if album_name == "\u5355\u66f2/\u672a\u77e5\u4e13\u8f91":
            query = query.filter((MusicFile.album.is_(None)) | (MusicFile.album == ""))
        else:
            query = query.filter(MusicFile.album == album_name)

    if album_artist or album_name:
        return query.order_by(MusicFile.disc_number.asc().nullsfirst(),
                              MusicFile.track_number.asc().nullsfirst(),
                              MusicFile.id.asc()).all()
    return query.order_by(MusicFile.created_at.desc()).limit(limit).all()


# ---------------------------------------------------------------------------
# Tool callable signature
# ---------------------------------------------------------------------------

# preview: (session, files, options) -> ToolPreview
PreviewFn = Callable[[Session, list[MusicFile], dict[str, Any]], ToolPreview]
# apply: (session, files, options, on_progress) -> dict (summary)
ApplyFn = Callable[[Session, list[MusicFile], dict[str, Any], Callable[[int, str], None]], dict]
