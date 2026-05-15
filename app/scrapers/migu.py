"""Migu Music scraper."""
import logging
import requests
from typing import Optional
from app.scrapers.base import BaseScraper, MusicMeta

logger = logging.getLogger(__name__)


class MiguScraper(BaseScraper):
    """Migu Music metadata scraper."""

    name = "migu"
    SEARCH_URL = "https://m.music.migu.cn/migu/remoting/scr_search_tag"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Referer": "https://m.music.migu.cn/",
        })

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        """Search Migu for metadata."""
        keyword = f"{artist} {title}".strip() if artist else title
        try:
            resp = self._session.get(
                self.SEARCH_URL,
                params={"keyword": keyword, "type": 2, "pgc": 1, "rows": 5},
                timeout=10,
            )
            data = resp.json()
            songs = data.get("musics", [])
            results = []
            for s in songs:
                meta = MusicMeta(
                    title=s.get("songName", ""),
                    artist=s.get("singerName", ""),
                    album=s.get("albumName", ""),
                    song_id="",
                    source="migu",
                )
                # Cover
                cover = s.get("cover", "")
                if cover and not cover.startswith("http"):
                    cover = "https:" + cover
                meta.cover_url = cover
                # Lyrics URL
                lyric_url = s.get("lyricUrl", "")
                if lyric_url and not lyric_url.startswith("http"):
                    lyric_url = "https:" + lyric_url
                meta.song_id = lyric_url
                meta._lyric_url = lyric_url
                results.append(meta)
            return results
        except Exception as e:
            logger.warning(f"[migu] Search failed: {e}")
            return []

    def get_lyrics(self, song_id: str) -> str:
        """Get lyrics from URL."""
        if not song_id:
            return ""
        try:
            resp = self._session.get(song_id, timeout=10)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
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
