"""Models for the PT search chain."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.sites.base import TorrentInfo


@dataclass
class SearchRequest:
    """Inbound search request used by the chain."""
    keyword: str
    sites: list[str] = field(default_factory=list)
    type: str = "keyword"          # keyword/artist/song/album
    artist: str = ""
    album: str = ""
    title: str = ""
    quality: str = "any"           # any/flac/mp3
    limit: int = 60                # cap aggregated results returned
    timeout: float = 15            # per-site timeout seconds


@dataclass
class QueryPlan:
    """One concrete query string sent to a site."""
    keyword: str
    mode: str = "exact"            # exact/dash/reverse/broad
    weight: float = 1.0


@dataclass
class SiteSearchStatus:
    """Per-site execution outcome surfaced to the UI."""
    site: str
    ok: bool = True
    count: int = 0
    seconds: float = 0.0
    error: str = ""
    queries: list[str] = field(default_factory=list)


@dataclass
class ScoredTorrent:
    """A normalized + scored torrent candidate."""
    torrent: TorrentInfo
    score: float = 0.0
    quality: str = ""              # detected media quality e.g. FLAC/MP3-320
    media_format: str = ""         # FLAC/MP3/M4A/...
    is_video_like: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class SearchResponse:
    """Aggregated chain response."""
    results: list[ScoredTorrent] = field(default_factory=list)
    sites: list[SiteSearchStatus] = field(default_factory=list)
    queries: list[QueryPlan] = field(default_factory=list)
    total: int = 0

    def to_legacy(self) -> list[TorrentInfo]:
        """Flatten to a plain TorrentInfo list for legacy callers."""
        return [item.torrent for item in self.results]
