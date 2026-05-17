"""Kuwo Music scraper adapted from music-tag-web."""
from __future__ import annotations

import hashlib
import logging
import random
from typing import Optional

import requests

from app.scrapers.base import BaseScraper, MusicMeta

logger = logging.getLogger(__name__)


class KuwoScraper(BaseScraper):
    """Kuwo metadata scraper."""

    name = "kuwo"
    SEARCH_URL = "http://www.kuwo.cn/api/www/search/searchMusicBykeyWord"
    LYRIC_URL = "http://kuwo.cn/newh5/singles/songinfoandlrc"

    def __init__(self):
        self._session = requests.Session()
        self._token = self._generate_token()
        sha1 = hashlib.sha1(self._token.encode("utf-8")).hexdigest()
        self._cross = hashlib.md5(sha1.encode("utf-8")).hexdigest()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "http://www.kuwo.cn/",
            "Cross": self._cross,
            "Cookie": f"Hm_token={self._token}",
        })

    @staticmethod
    def _generate_token(length: int = 32) -> str:
        charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return "".join(random.choices(charset, k=length))

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        keyword = f"{artist} {title}".strip() if artist else title
        try:
            resp = self._session.get(
                self.SEARCH_URL,
                params={"key": keyword, "pn": 1, "rn": 10, "httpsStatus": 1},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            songs = data.get("data", {}).get("list", []) or []
        except Exception as e:
            logger.warning(f"[kuwo] Search failed: {e}")
            return []

        results: list[MusicMeta] = []
        for song in songs[:10]:
            results.append(MusicMeta(
                title=song.get("name", ""),
                artist=song.get("artist", ""),
                album=song.get("album", ""),
                album_artist=song.get("artist", ""),
                year=0,
                cover_url=song.get("albumpic", ""),
                song_id=str(song.get("rid", "")),
                source=self.name,
            ))
        return results

    def get_lyrics(self, song_id: str) -> str:
        if not song_id:
            return ""
        try:
            resp = self._session.get(
                self.LYRIC_URL,
                params={"musicId": song_id, "mid": song_id, "type": "music", "httpsStatus": 1, "plat": "web_www"},
                timeout=10,
            )
            data = resp.json()
            lines = data.get("data", {}).get("lrclist", []) or []
            lyric = []
            for line in lines:
                seconds = int(float(line.get("time", "0") or 0))
                minute, sec = divmod(seconds, 60)
                lyric.append(f"[{minute:02d}:{sec:02d}.00]{line.get('lineLyric', '')}")
            return "\n".join(lyric)
        except Exception as e:
            logger.warning(f"[kuwo] Get lyrics failed: {e}")
            return ""

    def get_cover(self, url: str) -> Optional[bytes]:
        if not url:
            return None
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
        except Exception:
            pass
        return None
