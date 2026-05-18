"""QQ Music scraper adapted from music-tag-web musicu.fcg implementation."""
from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Optional

import requests

from app.scrapers.base import BaseScraper, MusicMeta, parse_duration_seconds

logger = logging.getLogger(__name__)


class QQMusicScraper(BaseScraper):
    """QQ Music metadata scraper using the newer musicu.fcg search API."""

    name = "qqmusic"
    SEARCH_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
    LYRIC_URL = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
    COVER_URL = "https://y.qq.com/music/photo_new/T002R500x500M000{mid}.jpg"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            # Keep headers Latin-1 encodable for requests/urllib3.
            "User-Agent": "QQMusic/73222 CFNetwork/1406.0.3 Darwin/22.4.0",
            "Referer": "https://y.qq.com/portal/profile.html",
            "Content-Type": "application/json;charset=utf-8",
        })

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        keyword = f"{artist} {title}".strip() if artist else title
        payload = {
            "comm": {
                "wid": "",
                "tmeAppID": "qqmusic",
                "authst": "",
                "uid": "",
                "gray": "0",
                "OpenUDID": "2d484d3157d4ed482e406e6c5fdcf8c3d3275deb",
                "ct": "6",
                "patch": "2",
                "psrf_qqopenid": "",
                "sid": "",
                "psrf_access_token_expiresAt": "",
                "cv": "80600",
                "gzip": "0",
                "qq": "",
                "nettype": "2",
                "psrf_qqunionid": "",
                "psrf_qqaccess_token": "",
                "tmeLoginType": "2",
            },
            "music.search.SearchCgiService.DoSearchForQQMusicDesktop": {
                "module": "music.search.SearchCgiService",
                "method": "DoSearchForQQMusicDesktop",
                "param": {
                    "num_per_page": 10,
                    "page_num": 1,
                    "remoteplace": "txt.mac.search",
                    "search_type": 0,
                    "query": keyword,
                    "grp": 1,
                    "searchid": str(uuid.uuid1()),
                    "nqc_flag": 0,
                },
            },
        }
        try:
            resp = self._session.post(self.SEARCH_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=10)
            resp.raise_for_status()
            data = resp.json()
            search_data = data["music.search.SearchCgiService.DoSearchForQQMusicDesktop"]["data"]
            songs = search_data.get("body", {}).get("song", {}).get("list", []) or []
        except Exception as e:
            logger.error(f"[qqmusic] Search failed: {e}")
            return []

        results: list[MusicMeta] = []
        for song in songs[:10]:
            singers = song.get("singer", []) or []
            artist_name = "/".join(s.get("name", "") for s in singers if s.get("name"))
            album_info = song.get("album", {}) or {}
            album_mid = album_info.get("mid", "")
            year = 0
            time_public = song.get("time_public", "") or ""
            if len(time_public) >= 4 and time_public[:4].isdigit():
                year = int(time_public[:4])
            file_info = song.get("file", {}) or {}
            results.append(MusicMeta(
                title=song.get("title", "") or song.get("name", ""),
                artist=artist_name,
                album=(album_info.get("title", "") or "").strip(),
                album_artist=artist_name,
                year=year,
                track_number=song.get("index_album", 0) or 0,
                cover_url=self.COVER_URL.format(mid=album_mid) if album_mid else "",
                song_id=song.get("mid", "") or file_info.get("media_mid", ""),
                album_id=album_mid,
                duration=parse_duration_seconds(song.get("interval") or song.get("duration")),
                size=int(file_info.get("size_flac") or file_info.get("size_320mp3") or file_info.get("size_128mp3") or 0),
                quality="flac" if file_info.get("size_flac") else ("320" if file_info.get("size_320mp3") else ""),
                provider_extra={"album_mid": album_mid, "media_mid": file_info.get("media_mid", "")},
                source=self.name,
            ))
        return results

    def get_lyrics(self, song_id: str) -> str:
        if not song_id:
            return ""
        params = {
            "g_tk": 5381,
            "format": "json",
            "inCharset": "utf-8",
            "outCharset": "utf-8",
            "notice": 0,
            "platform": "h5",
            "needNewCode": 1,
            "ct": 121,
            "cv": 0,
            "songmid": song_id,
        }
        try:
            resp = self._session.get(self.LYRIC_URL, params=params, timeout=10)
            data = resp.json()
            lyric = data.get("lyric", "")
            # QQ often returns base64 unless nobase64=1 is respected by the old endpoint.
            if lyric and not lyric.lstrip().startswith("["):
                try:
                    lyric = base64.b64decode(lyric).decode("utf-8")
                except Exception:
                    pass
            return lyric
        except Exception as e:
            logger.error(f"[qqmusic] Get lyrics failed: {e}")
            return ""

    def get_cover(self, url: str) -> Optional[bytes]:
        if not url:
            return None
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            if len(resp.content) > 1000:
                return resp.content
        except Exception as e:
            logger.error(f"[qqmusic] Get cover failed: {e}")
        return None
