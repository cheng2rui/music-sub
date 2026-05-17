"""Migu Music scraper.

主接口：https://pd.musicapp.migu.cn/MIGUM2.0/v1.0/content/search_all.do
该接口（PC 端搜索）返回 JSON，比 m.music.migu.cn 反爬轻很多。
歌词与封面回退到 music.migu.cn 提供的 v3 接口。
"""
import logging
import json
import requests
from typing import Optional

from app.scrapers.base import BaseScraper, MusicMeta

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://music.migu.cn/",
}


class MiguScraper(BaseScraper):
    """Migu Music metadata scraper."""

    name = "migu"
    SEARCH_URL = "https://pd.musicapp.migu.cn/MIGUM2.0/v1.0/content/search_all.do"
    LYRIC_URL = "https://music.migu.cn/v3/api/music/audioPlayer/getLyric"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        keyword = f"{artist} {title}".strip() if artist else title
        if not keyword:
            return []
        params = {
            "pageNo": 1,
            "pageSize": 10,
            "text": keyword,
            "searchSwitch": json.dumps({"song": 1}),
        }
        try:
            resp = self._session.get(self.SEARCH_URL, params=params, timeout=10)
        except Exception as e:
            logger.warning(f"[migu] HTTP error: {e}")
            return []
        if resp.status_code != 200:
            logger.warning(f"[migu] HTTP {resp.status_code}")
            return []
        try:
            data = resp.json()
        except Exception as e:
            logger.warning(f"[migu] decode failed ({len(resp.content)} bytes): {e}")
            return []
        if (data or {}).get("code") not in ("000000", 200, "200"):
            return []
        result = ((data.get("songResultData") or {}).get("result")) or []
        out: list[MusicMeta] = []
        for song in result[:8]:
            singers = song.get("singers") or []
            artist_name = "/".join(s.get("name", "") for s in singers if s.get("name"))
            albums = song.get("albums") or []
            album_name = albums[0].get("name", "") if albums else (song.get("album") or "")
            cover = ""
            cover_imgs = song.get("albumImgs") or song.get("songImgs") or []
            if cover_imgs:
                cover = cover_imgs[0].get("img") or ""
            if cover and not cover.startswith("http"):
                cover = "https:" + cover
            song_id = str(song.get("copyrightId") or song.get("id") or "")
            year = ""
            release_date = song.get("releaseDate") or song.get("publishTime") or ""
            if isinstance(release_date, str) and len(release_date) >= 4:
                year = release_date[:4]
            try:
                year_int = int(year) if year else 0
            except Exception:
                year_int = 0
            out.append(MusicMeta(
                title=song.get("name", "") or song.get("songName", ""),
                artist=artist_name or song.get("singer", ""),
                album=album_name,
                album_artist=artist_name,
                cover_url=cover,
                song_id=song_id,
                year=year_int,
                source=self.name,
            ))
        return out

    def get_lyrics(self, song_id: str) -> str:
        if not song_id:
            return ""
        try:
            resp = self._session.get(
                self.LYRIC_URL,
                params={"copyrightId": song_id},
                timeout=10,
            )
            data = resp.json()
            return data.get("lyric", "") or ""
        except Exception as e:
            logger.warning(f"[migu] lyric fetch failed: {e}")
        return ""

    def get_cover(self, url: str) -> Optional[bytes]:
        if not url:
            return None
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
        except Exception as e:
            logger.warning(f"[migu] cover fetch failed: {e}")
        return None
