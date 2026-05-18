"""Kugou Music scraper adapted from music-tag-web complexsearch API."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Optional

import requests

from app.scrapers.base import BaseScraper, MusicMeta, parse_duration_seconds

logger = logging.getLogger(__name__)


_TAG_RE = re.compile(r"</?em>")


def _strip_em(value: str | None) -> str:
    return _TAG_RE.sub("", value or "")


class KugouScraper(BaseScraper):
    """Kugou metadata scraper using signed complexsearch endpoint."""

    name = "kugou"
    SEARCH_URL = "https://complexsearch.kugou.com/v2/search/song"
    LYRIC_URL = "http://m.kugou.com/app/i/krc.php"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.kugou.com/",
        })

    @staticmethod
    def _signature(keyword: str, millis: str) -> str:
        text = (
            "NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt"
            f"bitrate=0clienttime={millis}clientver=2000dfid=-inputtype=0"
            f"iscorrection=1isfuzzy=0keyword={keyword}mid={millis}page=1pagesize=10"
            "platform=WebFilterprivilege_filter=0srcappid=2919tag=emuserid=-1"
            f"uuid={millis}"
            "NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt"
        )
        return hashlib.md5(text.encode("utf-8")).hexdigest().upper()

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        keyword = f"{artist} {title}".strip() if artist else title
        millis = str(round(time.time() * 1000))
        params = {
            "keyword": keyword,
            "page": 1,
            "pagesize": 10,
            "bitrate": 0,
            "isfuzzy": 0,
            "tag": "em",
            "inputtype": 0,
            "platform": "WebFilter",
            "userid": -1,
            "clientver": 2000,
            "iscorrection": 1,
            "privilege_filter": 0,
            "srcappid": 2919,
            "clienttime": millis,
            "mid": millis,
            "uuid": millis,
            "dfid": "-",
            "signature": self._signature(keyword, millis),
        }
        try:
            # Do not use the older mobilecdn endpoint: it currently has TLS hostname issues.
            resp = self._session.get(self.SEARCH_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            songs = data.get("data", {}).get("lists", []) or []
        except Exception as e:
            logger.warning(f"[kugou] Search failed: {e}")
            return []

        results: list[MusicMeta] = []
        for song in songs[:10]:
            artists = _strip_em(song.get("SingerName", "")).replace("、", "/")
            album_id = song.get("AlbumID")
            cover = song.get("Image", "") or ""
            if cover:
                try:
                    cover = cover.format(size=500)
                except Exception:
                    pass
            elif album_id:
                cover = f"https://imge.kugou.com/stdmusic/500/{album_id}.jpg"
            year = 0
            publish = song.get("PublishTime", "") or ""
            if len(publish) >= 4 and publish[:4].isdigit():
                year = int(publish[:4])
            results.append(MusicMeta(
                title=_strip_em(song.get("SongName", "")),
                artist=artists,
                album=song.get("AlbumName", "") or "",
                album_artist=artists,
                year=year,
                cover_url=cover,
                song_id=song.get("FileHash", "") or "",
                album_id=str(album_id or ""),
                duration=parse_duration_seconds(song.get("Duration") or song.get("duration")),
                size=int(song.get("FileSize") or song.get("FileSize_320") or song.get("SQFileSize") or 0),
                bitrate=int(song.get("Bitrate") or 0),
                quality="flac" if song.get("SQFileHash") else ("320" if song.get("HQFileHash") else ""),
                provider_extra={"album_id": album_id, "hash": song.get("FileHash")},
                source=self.name,
            ))
        return results

    def get_lyrics(self, song_id: str) -> str:
        if not song_id:
            return ""
        try:
            resp = self._session.get(self.LYRIC_URL, params={"cmd": 100, "timelength": 999999, "hash": song_id}, timeout=10)
            if resp.status_code == 200:
                resp.encoding = "utf-8"
                return resp.text
        except Exception as e:
            logger.warning(f"[kugou] Get lyrics failed: {e}")
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
