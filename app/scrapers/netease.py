"""NetEase Cloud Music scraper.

主接口走 GET https://music.163.com/api/search/get/web (公开 JSON 接口)，
回退到 weapi 加密接口 (借鉴 music-tag-web)。
歌词走 linuxapi forward。
"""
import json
import base64
import binascii
import logging
import os
import random
import requests
from typing import Optional
from Crypto.Cipher import AES

from app.scrapers.base import BaseScraper, MusicMeta, parse_duration_seconds

logger = logging.getLogger(__name__)


# ---- weapi crypto constants (mtw 同款) ----
NONCE = b"0CoJUm6Qyw8W8jud"
PUB_KEY = "010001"
MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
    "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
    "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
    "575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b"
    "3ece0462db0a22b8e7"
)
LINUX_KEY = b"rFgB&h#%2?^eDg:Q"
IV = b"0102030405060708"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
]


def _aes_cbc(text: bytes, key: bytes, *, base64_out: bool = True) -> bytes:
    pad = 16 - len(text) % 16
    text = text + bytes([pad]) * pad
    cipher = AES.new(key, AES.MODE_CBC, IV)
    out = cipher.encrypt(text)
    return base64.b64encode(out) if base64_out else binascii.hexlify(out).upper()


def _aes_ecb_hex(text: bytes, key: bytes) -> bytes:
    pad = 16 - len(text) % 16
    text = text + bytes([pad]) * pad
    cipher = AES.new(key, AES.MODE_ECB)
    return binascii.hexlify(cipher.encrypt(text)).upper()


def _rsa(secret: bytes) -> str:
    reversed_bytes = secret[::-1]
    rs = pow(int(binascii.hexlify(reversed_bytes), 16), int(PUB_KEY, 16), int(MODULUS, 16))
    return format(rs, "x").zfill(256)


def we_encrypt(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    secret = binascii.hexlify(os.urandom(16))[:16]
    params = _aes_cbc(_aes_cbc(data, NONCE), secret)
    enc_sec_key = _rsa(secret)
    return {"params": params.decode(), "encSecKey": enc_sec_key}


def linux_encrypt(payload: dict) -> dict:
    text = json.dumps(payload).encode("utf-8")
    return {"eparams": _aes_ecb_hex(text, LINUX_KEY).decode()}


class NetEaseScraper(BaseScraper):
    """NetEase Cloud Music metadata scraper.

    Strategy:
    1. Try public GET /api/search/get/web - 不需要加密，返回 JSON
    2. 如果失败，回退到 weapi 加密 POST
    3. 歌词通过 linuxapi forward 拉
    """

    name = "netease"
    BASE_URL = "https://music.163.com"
    PUBLIC_SEARCH_URL = "https://music.163.com/api/search/get/web"
    WEAPI_SEARCH_URL = "https://music.163.com/weapi/cloudsearch/get/web"
    LINUX_FORWARD_URL = "https://music.163.com/api/linux/forward"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://music.163.com/",
        })

    def _public_search(self, keyword: str) -> list[dict]:
        try:
            resp = self._session.get(
                self.PUBLIC_SEARCH_URL,
                params={"s": keyword, "type": 1, "limit": 10, "offset": 0},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"[netease] public search HTTP error: {e}")
            return []
        if resp.status_code != 200 or not resp.content:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        return (data.get("result") or {}).get("songs") or []

    def _weapi_search(self, keyword: str) -> list[dict]:
        encrypted = we_encrypt({
            "s": keyword,
            "type": "1",
            "limit": "10",
            "offset": "0",
        })
        try:
            resp = self._session.post(
                self.WEAPI_SEARCH_URL,
                data=encrypted,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"[netease] weapi search HTTP error: {e}")
            return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        return (data.get("result") or {}).get("songs") or []

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        keyword = f"{artist} {title}".strip() if artist else title
        if not keyword:
            return []
        songs = self._public_search(keyword) or self._weapi_search(keyword)
        out: list[MusicMeta] = []
        for song in songs[:8]:
            artists = song.get("artists") or song.get("ar") or []
            artist_name = "/".join(a.get("name", "") for a in artists) if artists else ""
            album = song.get("album") or song.get("al") or {}
            year = 0
            pub_time = (
                song.get("publishTime")
                or (album or {}).get("publishTime")
                or 0
            )
            if pub_time:
                try:
                    from datetime import datetime
                    year = datetime.fromtimestamp(pub_time / 1000).year
                except Exception:
                    year = 0
            cover_url = (
                (album or {}).get("picUrl")
                or (album or {}).get("blurPicUrl")
                or ""
            )
            out.append(MusicMeta(
                title=song.get("name", ""),
                artist=artist_name,
                album=(album or {}).get("name", ""),
                album_artist=artist_name,
                year=year,
                cover_url=cover_url,
                song_id=str(song.get("id") or ""),
                album_id=str((album or {}).get("id") or ""),
                duration=parse_duration_seconds(song.get("duration") or song.get("dt")),
                provider_extra={"album_id": (album or {}).get("id")},
                source=self.name,
            ))
        # /api/search/get/web 不返回 picUrl，需要再调一次 /api/song/detail 把封面拼上
        missing_ids = [m.song_id for m in out if m.song_id and not m.cover_url]
        if missing_ids:
            covers = self._fetch_covers(missing_ids)
            for m in out:
                if not m.cover_url and m.song_id in covers:
                    m.cover_url = covers[m.song_id]
        return out

    def _fetch_covers(self, song_ids: list[str]) -> dict[str, str]:
        if not song_ids:
            return {}
        try:
            ids_param = "[" + ",".join(song_ids) + "]"
            resp = self._session.get(
                "https://music.163.com/api/song/detail/",
                params={"ids": ids_param},
                timeout=10,
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
        except Exception as e:
            logger.warning(f"[netease] song detail failed: {e}")
            return {}
        covers: dict[str, str] = {}
        for song in (data.get("songs") or []):
            album = song.get("album") or {}
            cover = album.get("picUrl") or album.get("blurPicUrl") or ""
            if cover:
                covers[str(song.get("id"))] = cover
        return covers


    def get_lyrics(self, song_id: str) -> str:
        if not song_id:
            return ""
        # 公共 GET 接口
        try:
            resp = self._session.get(
                "https://music.163.com/api/song/lyric",
                params={"id": song_id, "lv": -1, "kv": -1, "tv": -1},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                lyric = (data.get("lrc") or {}).get("lyric", "") or ""
                if lyric:
                    return lyric
        except Exception as e:
            logger.warning(f"[netease] lyric public failed: {e}")
        # linuxapi fallback
        encrypted = linux_encrypt({
            "method": "POST",
            "url": "https://music.163.com/api/song/lyric?lv=-1&kv=-1&tv=-1",
            "params": {"id": song_id},
        })
        try:
            resp = self._session.post(self.LINUX_FORWARD_URL, data=encrypted, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return (data.get("lrc") or {}).get("lyric", "") or ""
        except Exception as e:
            logger.warning(f"[netease] lyric linuxapi failed: {e}")
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
            logger.warning(f"[netease] Get cover failed: {e}")
        return None
