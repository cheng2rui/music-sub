"""QQ Music scraper."""
import logging
import requests
from typing import Optional
from app.scrapers.base import BaseScraper, MusicMeta

logger = logging.getLogger(__name__)


class QQMusicScraper(BaseScraper):
    """QQ Music metadata scraper using public search API."""

    name = "qqmusic"
    SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
    LYRIC_URL = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
    COVER_URL = "https://y.gtimg.cn/music/photo_new/T002R500x500M000{mid}.jpg"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://y.qq.com/",
        })

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        """Search QQ Music for metadata."""
        keyword = f"{artist} {title}".strip() if artist else title
        params = {
            "w": keyword,
            "format": "json",
            "p": 1,
            "n": 10,
            "cr": 1,
            "new_json": 1,
        }
        try:
            resp = self._session.get(self.SEARCH_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"[qqmusic] Search failed: {e}")
            return []

        results = []
        songs = data.get("data", {}).get("song", {}).get("list", [])
        for song in songs[:5]:
            singers = song.get("singer", [])
            artist_name = "/".join(s.get("name", "") for s in singers) if singers else ""
            album_info = song.get("album", {})
            album_mid = album_info.get("mid", "")

            results.append(MusicMeta(
                title=song.get("name", ""),
                artist=artist_name,
                album=album_info.get("name", ""),
                album_artist=artist_name,
                year=0,
                genre="",
                track_number=song.get("index_album", 0),
                cover_url=self.COVER_URL.format(mid=album_mid) if album_mid else "",
                song_id=song.get("mid", "") or song.get("songmid", ""),
                source=self.name,
            ))
        return results

    def get_lyrics(self, song_id: str) -> str:
        """Get lyrics from QQ Music."""
        params = {
            "songmid": song_id,
            "format": "json",
            "nobase64": 1,
        }
        try:
            resp = self._session.get(self.LYRIC_URL, params=params, timeout=10)
            data = resp.json()
            return data.get("lyric", "")
        except Exception as e:
            logger.error(f"[qqmusic] Get lyrics failed: {e}")
            return ""

    def get_cover(self, url: str) -> Optional[bytes]:
        """Download cover image."""
        if not url:
            return None
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            if len(resp.content) > 1000:  # Valid image
                return resp.content
            return None
        except Exception as e:
            logger.error(f"[qqmusic] Get cover failed: {e}")
            return None
