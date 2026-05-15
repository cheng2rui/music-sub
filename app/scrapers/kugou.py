"""Kugou Music scraper."""
import logging
import hashlib
import requests
from typing import Optional
from app.scrapers.base import BaseScraper, MusicMeta

logger = logging.getLogger(__name__)


class KugouScraper(BaseScraper):
    """Kugou Music metadata scraper."""

    name = "kugou"
    SEARCH_URL = "https://mobilecdn.kugou.com/api/v3/search/song"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        """Search Kugou for metadata."""
        keyword = f"{artist} {title}".strip() if artist else title
        try:
            resp = self._session.get(
                self.SEARCH_URL,
                params={"keyword": keyword, "page": 1, "pagesize": 5, "showtype": 1},
                timeout=10,
            )
            data = resp.json()
            songs = data.get("data", {}).get("info", [])
            results = []
            for s in songs:
                meta = MusicMeta(
                    title=s.get("songname", ""),
                    artist=s.get("singername", ""),
                    album=s.get("album_name", ""),
                    duration=s.get("duration", 0),
                    source="kugou",
                )
                # Album cover from album_id
                album_id = s.get("album_id")
                if album_id:
                    meta.cover_url = f"https://imge.kugou.com/stdmusic/150/{album_id}.jpg"
                results.append(meta)
            return results
        except Exception as e:
            logger.warning(f"[kugou] Search failed: {e}")
            return []

    def get_lyrics(self, song_id: str) -> str:
        """Get lyrics (not implemented for kugou basic)."""
        return ""

    def get_cover(self, url: str) -> Optional[bytes]:
        """Download cover image."""
        if not url:
            return None
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
        except Exception:
            pass
        return None
