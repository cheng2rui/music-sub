"""NetEase Cloud Music scraper (借鉴 music-tag-web)."""
import json
import base64
import logging
import requests
from typing import Optional
from Crypto.Cipher import AES
from app.scrapers.base import BaseScraper, MusicMeta

logger = logging.getLogger(__name__)

# NetEase API encryption constants
NONCE = b"0CoJUm6Qyw8W8jud"
PUB_KEY = "010001"
MODULUS = "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
IV = b"0102030405060708"


def _aes_encrypt(text: str, key: bytes) -> str:
    pad = 16 - len(text) % 16
    text = text + chr(pad) * pad
    cipher = AES.new(key, AES.MODE_CBC, IV)
    encrypted = cipher.encrypt(text.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def _create_params(data: dict) -> dict:
    """Create encrypted params for NetEase API."""
    text = json.dumps(data)
    enc_text = _aes_encrypt(text, NONCE)
    sec_key = "F" * 16  # Simplified; full impl uses random key + RSA
    enc_text = _aes_encrypt(enc_text, sec_key.encode())
    return {
        "params": enc_text,
        "encSecKey": "0" * 256,  # Simplified placeholder
    }


class NetEaseScraper(BaseScraper):
    """NetEase Cloud Music metadata scraper."""

    name = "netease"
    BASE_URL = "https://music.163.com"
    SEARCH_URL = "https://music.163.com/weapi/cloudsearch/get/web"
    LYRIC_URL = "https://music.163.com/api/song/lyric"
    COVER_PREFIX = ""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://music.163.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        })

    def search(self, title: str, artist: str = "") -> list[MusicMeta]:
        """Search NetEase for metadata."""
        keyword = f"{artist} {title}".strip() if artist else title
        data = {"s": keyword, "type": "1", "limit": "10", "offset": "0"}
        params = _create_params(data)
        try:
            resp = self._session.post(self.SEARCH_URL, data=params, timeout=10)
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            logger.error(f"[netease] Search failed: {e}")
            return []

        results = []
        songs = result.get("result", {}).get("songs", [])
        for song in songs[:5]:
            artists = song.get("ar", [])
            artist_name = "/".join(a.get("name", "") for a in artists) if artists else ""
            album = song.get("al", {})
            year = 0
            pub_time = song.get("publishTime", 0)
            if pub_time:
                from datetime import datetime
                try:
                    year = datetime.fromtimestamp(pub_time / 1000).year
                except Exception:
                    pass

            results.append(MusicMeta(
                title=song.get("name", ""),
                artist=artist_name,
                album=album.get("name", ""),
                album_artist=artist_name,
                year=year,
                cover_url=album.get("picUrl", ""),
                song_id=str(song.get("id", "")),
                source=self.name,
            ))
        return results

    def get_lyrics(self, song_id: str) -> str:
        """Get lyrics from NetEase."""
        params = {"id": song_id, "lv": -1, "kv": -1, "tv": -1}
        try:
            resp = self._session.get(self.LYRIC_URL, params=params, timeout=10)
            data = resp.json()
            return data.get("lrc", {}).get("lyric", "")
        except Exception as e:
            logger.error(f"[netease] Get lyrics failed: {e}")
            return ""

    def get_cover(self, url: str) -> Optional[bytes]:
        """Download cover image."""
        if not url:
            return None
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            if len(resp.content) > 1000:
                return resp.content
            return None
        except Exception as e:
            logger.error(f"[netease] Get cover failed: {e}")
            return None
