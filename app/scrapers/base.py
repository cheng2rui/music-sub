"""Base class for music metadata scrapers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MusicMeta:
    """Unified music metadata result."""
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: int = 0
    genre: str = ""
    track_number: int = 0
    disc_number: int = 1
    cover_url: str = ""
    cover_data: Optional[bytes] = None
    song_id: str = ""       # provider-specific song id, used for lyrics
    album_id: str = ""      # provider-specific album id, used to lock album-level matching
    lyrics: str = ""
    duration: float = 0.0   # seconds
    size: int = 0           # bytes, when provider exposes it
    bitrate: int = 0        # kbps, when provider exposes it
    quality: str = ""       # provider quality label, e.g. flac/320/vip
    provider_extra: dict[str, Any] = field(default_factory=dict)
    source: str = ""


def parse_duration_seconds(value: Any) -> float:
    """Best-effort parse of provider duration values into seconds."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        raw = float(value)
        # Most provider millisecond fields are named duration/dt but arrive as large ints.
        return raw / 1000.0 if raw > 10000 else raw
    text = str(value).strip()
    if not text:
        return 0.0
    if ":" in text:
        try:
            parts = [float(p) for p in text.split(":")]
            total = 0.0
            for part in parts:
                total = total * 60 + part
            return total
        except Exception:
            return 0.0
    try:
        raw = float(text)
        return raw / 1000.0 if raw > 10000 else raw
    except Exception:
        return 0.0


class BaseScraper(ABC):
    """Base class for metadata scrapers."""

    name: str = "base"

    @abstractmethod
    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        """Search for music metadata by title and optional artist."""
        ...

    @abstractmethod
    def get_lyrics(self, song_id: str) -> str:
        """Get lyrics by song ID."""
        ...

    @abstractmethod
    def get_cover(self, url: str) -> Optional[bytes]:
        """Download cover image."""
        ...
