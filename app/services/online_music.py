"""Online music search/download helpers inspired by musicn/go-music-dl.

This module provides lightweight built-in direct download support for a few
public music sources. It intentionally keeps a unified result shape so the UI
can later swap to go-music-dl/musicn CLI without changing the frontend API.
"""
import hashlib
import logging
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

import requests

from app.config import config

logger = logging.getLogger(__name__)


@dataclass
class OnlineSong:
    source: str
    song_id: str
    title: str
    artist: str
    album: str = ""
    filename: str = ""
    url: str = ""
    lyric_url: str = ""
    cover_url: str = ""
    size: int = 0
    format: str = "mp3"
    disabled: bool = False

    def to_dict(self):
        return asdict(self)


_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})


def _clean_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "", name or "")
    name = re.sub(r"\s+", " ", name).strip()
    return name or "unknown"


def _head_size(url: str) -> int:
    if not url:
        return 0
    try:
        resp = _SESSION.head(url, allow_redirects=True, timeout=10)
        if resp.status_code < 400:
            return int(resp.headers.get("content-length") or 0)
    except Exception:
        pass
    return 0


def search_migu(keyword: str, limit: int = 20) -> list[OnlineSong]:
    """Search Migu and resolve downloadable URLs."""
    try:
        resp = _SESSION.get(
            "https://pd.musicapp.migu.cn/MIGUM3.0/v1.0/content/search_all.do",
            params={"text": keyword, "pageNo": 1, "pageSize": limit, "searchSwitch": "{song:1}"},
            timeout=15,
        )
        data = resp.json()
        rows = data.get("songResultData", {}).get("result", []) or []
    except Exception as e:
        logger.warning(f"[online:migu] search failed: {e}")
        return []

    results: list[OnlineSong] = []
    for row in rows[:limit]:
        try:
            copyright_id = row.get("copyrightId") or row.get("copyrightID")
            if not copyright_id:
                continue
            detail = _SESSION.get(
                "https://c.musicapp.migu.cn/MIGUM2.0/v1.0/content/resourceinfo.do",
                params={"copyrightId": copyright_id, "resourceType": 0},
                timeout=15,
            ).json()
            resource = (detail.get("resource") or [{}])[0]
            audio_url = resource.get("audioUrl") or ""
            if not audio_url:
                continue
            path = unquote(urlparse(audio_url).path)
            dl_url = f"https://freetyst.nf.migu.cn{path}".replace("彩铃/6_mp3-128kbps", "标准高清/MP3_320_16_Stero")
            artists = row.get("singers") or row.get("artists") or []
            artist = "/".join(a.get("name", "") for a in artists if isinstance(a, dict)) or row.get("singerName", "")
            title = row.get("name") or row.get("songName") or ""
            cover = ""
            imgs = row.get("imgItems") or []
            if imgs:
                cover = imgs[0].get("img", "")
            ext = "flac" if ".flac" in dl_url.lower() else "mp3"
            size = _head_size(dl_url)
            lyric_url = row.get("lyricUrl") or ""
            if lyric_url and not lyric_url.startswith("http"):
                lyric_url = "https:" + lyric_url
            results.append(OnlineSong(
                source="migu",
                song_id=str(copyright_id),
                title=title,
                artist=artist,
                album=row.get("albumName", ""),
                filename=f"{_clean_filename(title)} - {_clean_filename(artist)}.{ext}",
                url=dl_url,
                lyric_url=lyric_url,
                cover_url=cover,
                size=size,
                format=ext,
                disabled=not bool(size),
            ))
        except Exception as e:
            logger.debug(f"[online:migu] skip item: {e}")
    return results


def search_kugou(keyword: str, limit: int = 20) -> list[OnlineSong]:
    """Search Kugou and resolve downloadable URLs."""
    try:
        resp = _SESSION.get(
            "http://msearchcdn.kugou.com/api/v3/search/song",
            params={"keyword": keyword, "page": 1, "pagesize": limit},
            timeout=15,
        )
        rows = resp.json().get("data", {}).get("info", []) or []
    except Exception as e:
        logger.warning(f"[online:kugou] search failed: {e}")
        return []

    results: list[OnlineSong] = []
    for row in rows[:limit]:
        try:
            h = row.get("hash") or row.get("320hash") or ""
            if not h:
                continue
            key = hashlib.md5(f"{h}kgcloudv2".encode()).hexdigest()
            info = _SESSION.get(
                "http://trackercdn.kugou.com/i/v2/",
                params={"key": key, "hash": h, "br": "hq", "appid": 1005, "pid": 2, "cmd": 25, "behavior": "play"},
                timeout=15,
            ).json()
            urls = info.get("url") or []
            dl_url = urls[0] if urls else ""
            filename = row.get("filename", "")
            if " - " in filename:
                artist, title = filename.split(" - ", 1)
            else:
                artist, title = row.get("singername", ""), row.get("songname", "")
            ext = "flac" if ".flac" in dl_url.lower() else "mp3"
            results.append(OnlineSong(
                source="kugou",
                song_id=str(h),
                title=title,
                artist=artist,
                album=row.get("album_name", ""),
                filename=f"{_clean_filename(title)} - {_clean_filename(artist)}.{ext}",
                url=dl_url,
                lyric_url=f"http://lyrics.kugou.com/search?ver=1&man=yes&client=pc&hash={h}",
                size=int(info.get("fileSize") or row.get("320filesize") or row.get("filesize") or 0),
                format=ext,
                disabled=not bool(dl_url),
            ))
        except Exception as e:
            logger.debug(f"[online:kugou] skip item: {e}")
    return results


def search_netease(keyword: str, limit: int = 20) -> list[OnlineSong]:
    """Search NetEase using public APIs. Some songs may not expose a playable URL."""
    try:
        resp = _SESSION.get(
            "https://music.163.com/api/search/get/web",
            params={"s": keyword, "type": 1, "limit": limit, "offset": 0},
            headers={"Referer": "https://music.163.com/"},
            timeout=15,
        )
        rows = resp.json().get("result", {}).get("songs", []) or []
    except Exception as e:
        logger.warning(f"[online:netease] search failed: {e}")
        return []

    results: list[OnlineSong] = []
    for row in rows[:limit]:
        try:
            sid = row.get("id")
            artists = row.get("artists") or []
            artist = "/".join(a.get("name", "") for a in artists)
            title = row.get("name", "")
            player = _SESSION.get(
                "https://music.163.com/api/song/enhance/player/url/v1",
                params={"id": sid, "ids": f"[{sid}]", "level": "standard", "encodeType": "mp3"},
                headers={"Referer": f"https://music.163.com/song?id={sid}"},
                timeout=15,
            ).json()
            item = (player.get("data") or [{}])[0]
            dl_url = item.get("url") or ""
            size = int(item.get("size") or 0)
            album_data = row.get("album") or {}
            album_name = album_data.get("name", "") if isinstance(album_data, dict) else str(album_data or "")
            results.append(OnlineSong(
                source="netease",
                song_id=str(sid),
                title=title,
                artist=artist,
                album=album_name,
                filename=f"{_clean_filename(title)} - {_clean_filename(artist)}.mp3",
                url=dl_url,
                lyric_url=f"https://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1",
                size=size,
                format="mp3",
                disabled=not bool(dl_url),
            ))
        except Exception as e:
            logger.debug(f"[online:netease] skip item: {e}")
    return results


def search_online(keyword: str, sources: list[str] | None = None, limit: int = 20) -> list[dict]:
    sources = sources or ["migu", "kugou", "netease"]
    results: list[OnlineSong] = []
    per_source = max(5, min(limit, 20))
    for src in sources:
        if src == "migu":
            results.extend(search_migu(keyword, per_source))
        elif src == "kugou":
            results.extend(search_kugou(keyword, per_source))
        elif src == "netease":
            results.extend(search_netease(keyword, per_source))
    # Prefer enabled/downloadable first, then larger files.
    results.sort(key=lambda x: (x.disabled, -(x.size or 0)))
    return [r.to_dict() for r in results[:limit]]


def download_online_song(song: dict) -> str:
    """Download an online song to config.paths.downloads/online and return file path."""
    url = song.get("url") or ""
    if not url:
        raise ValueError("没有可下载链接")

    filename = _clean_filename(song.get("filename") or f"{song.get('title','unknown')} - {song.get('artist','unknown')}.{song.get('format','mp3')}")
    target_dir = Path(config.paths.downloads) / "online"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename

    # Avoid overwriting existing files.
    if target.exists():
        stem, suffix = target.stem, target.suffix
        i = 1
        while target.exists():
            target = target_dir / f"{stem}({i}){suffix}"
            i += 1

    logger.info(f"[online:{song.get('source')}] Downloading {filename}")
    with _SESSION.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(target, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

    # Save source-provided lyrics if available. Pipeline scraping may improve/overwrite later.
    lyric_url = song.get("lyric_url") or ""
    if lyric_url:
        try:
            lyric_text = _SESSION.get(lyric_url, timeout=15).text
            if lyric_text and len(lyric_text) > 20:
                target.with_suffix(".lrc").write_text(lyric_text, encoding="utf-8")
        except Exception as e:
            logger.debug(f"[online:{song.get('source')}] lyric download failed: {e}")

    return str(target)
