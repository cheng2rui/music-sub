"""Base class for music metadata scrapers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


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
    lyrics: str = ""
    source: str = ""


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
