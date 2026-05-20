"""Helpers for stable album-level identity and folder ownership."""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import MusicFile

_UNKNOWN = {"", "unknown", "unknown artist", "未知艺人", "various artists"}
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:/|／|、|,|，|;|；|&|＆|\+|\|| feat\.? | ft\.? | featuring | with | x )\s*",
    re.IGNORECASE,
)


def norm_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"\s+", "", value)


def is_unknown_artist(value: str | None) -> bool:
    return (value or "").strip().lower() in _UNKNOWN


def primary_artist(value: str | None) -> str:
    """Return the first/primary artist from a multi-artist string."""
    text = (value or "").strip()
    if not text:
        return ""
    parts = [p.strip() for p in _ARTIST_SPLIT_RE.split(text) if p.strip()]
    return parts[0] if parts else text


def canonical_album_artist(db: Session, album: str | None, candidate: str | None = "", *, current_id: int | None = None) -> str:
    """Choose a stable folder artist for an album.

    If the album already exists in the library, use the first track's album artist
    (or track artist) so future downloads land in the same folder. Otherwise use
    the first singer from the candidate string.
    """
    album_key = norm_text(album)
    if album_key:
        q = db.query(MusicFile).filter(func.lower(func.replace(func.coalesce(MusicFile.album, ""), " ", "")) == album_key)
        if current_id:
            q = q.filter(MusicFile.id != current_id)
        rows = q.order_by(
            MusicFile.track_number.is_(None),
            MusicFile.track_number.asc(),
            MusicFile.id.asc(),
        ).limit(50).all()
        for row in rows:
            value = primary_artist(row.album_artist or row.artist)
            if value and not is_unknown_artist(value):
                return value
    fallback = primary_artist(candidate)
    return "" if is_unknown_artist(fallback) else fallback
