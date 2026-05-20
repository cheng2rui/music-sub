"""Online music search/download helpers inspired by musicn/go-music-dl.

This module provides lightweight built-in direct download support for a few
public music sources. It intentionally keeps a unified result shape so the UI
can later swap to go-music-dl/musicn CLI without changing the frontend API.
"""
import hashlib
import logging
import math
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

import requests

from app.config import config

logger = logging.getLogger(__name__)


class OnlineDownloadError(RuntimeError):
    """Structured online-download failure for user-facing diagnostics."""

    def __init__(self, message: str, *, reason: str = "download_failed", source: str = "online", details: dict | None = None):
        super().__init__(message)
        self.reason = reason
        self.source = source
        self.details = details or {}

    def to_detail(self) -> dict:
        return {"message": str(self), "reason": self.reason, "source": self.source, "details": self.details}


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
    duration: int = 0
    bitrate: int = 0
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
    """Search NetEase using public APIs. 优先试 lossless（FLAC），失败回落 standard mp3。"""
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
            album_data = row.get("album") or {}
            album_name = album_data.get("name", "") if isinstance(album_data, dict) else str(album_data or "")

            dl_url, size, ext = "", 0, "mp3"
            # 参考 music-lib netease: lossless > exhigh > standard。不带登录拿不到的会自动回落。
            for level, expect_ext in (("lossless", "flac"), ("exhigh", "mp3"), ("standard", "mp3")):
                try:
                    player = _SESSION.get(
                        "https://music.163.com/api/song/enhance/player/url/v1",
                        params={"id": sid, "ids": f"[{sid}]", "level": level, "encodeType": expect_ext},
                        headers={"Referer": f"https://music.163.com/song?id={sid}"},
                        timeout=15,
                    ).json()
                except Exception:
                    continue
                item = (player.get("data") or [{}])[0]
                url = item.get("url") or ""
                if not url:
                    continue
                dl_url = url
                size = int(item.get("size") or 0)
                # 以返回 URL 为准判断格式，防止服务器静默降级
                ext = "flac" if ".flac" in url.lower() else "mp3"
                break

            results.append(OnlineSong(
                source="netease",
                song_id=str(sid),
                title=title,
                artist=artist,
                album=album_name,
                filename=f"{_clean_filename(title)} - {_clean_filename(artist)}.{ext}",
                url=dl_url,
                lyric_url=f"https://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1",
                size=size,
                format=ext,
                disabled=not bool(dl_url),
            ))
        except Exception as e:
            logger.debug(f"[online:netease] skip item: {e}")
    return results


def _parse_kuwo_minfo(minfo: str) -> tuple[int, int, str]:
    """Parse Kuwo MINFO snippets for best known size/bitrate/format."""
    if not minfo:
        return 0, 0, "mp3"
    best_size, best_bitrate, best_fmt = 0, 0, "mp3"
    for part in re.split(r";|,", minfo):
        text = part.strip().lower()
        size = 0
        bitrate = 0
        fmt = "flac" if "flac" in text else "mp3"
        m = re.search(r"(\d+)k(?:mp3)?", text)
        if m:
            bitrate = int(m.group(1))
        sm = re.search(r"(?:size|filesize)[:=]?(\d+)", text)
        if sm:
            size = int(sm.group(1))
        score = (1 if fmt == "flac" else 0, bitrate, size)
        if score > (1 if best_fmt == "flac" else 0, best_bitrate, best_size):
            best_size, best_bitrate, best_fmt = size, bitrate, fmt
    return best_size, best_bitrate, best_fmt


def search_kuwo(keyword: str, limit: int = 20) -> list[OnlineSong]:
    """Search Kuwo and resolve downloadable URLs.

    Inspired by music-lib's Kuwo provider, but implemented independently in
    Python. Anonymous access may still be copyright/region restricted.
    """
    try:
        resp = _SESSION.get(
            "http://www.kuwo.cn/search/searchMusicBykeyWord",
            params={
                "vipver": "1",
                "client": "kt",
                "ft": "music",
                "cluster": "0",
                "strategy": "2012",
                "encoding": "utf8",
                "rformat": "json",
                "mobi": "1",
                "issubtitle": "1",
                "show_copyright_off": "1",
                "pn": "0",
                "rn": limit,
                "all": keyword,
            },
            timeout=15,
        )
        rows = resp.json().get("abslist", []) or []
    except Exception as e:
        logger.warning(f"[online:kuwo] search failed: {e}")
        return []

    results: list[OnlineSong] = []
    for row in rows[:limit]:
        try:
            rid = str(row.get("MUSICRID") or row.get("musicrid") or "").replace("MUSIC_", "")
            if not rid or int(row.get("bitSwitch") or 0) == 0:
                continue
            title = row.get("SONGNAME") or row.get("songname") or ""
            artist = row.get("ARTIST") or row.get("artist") or ""
            album = row.get("ALBUM") or row.get("album") or ""
            duration = int(row.get("DURATION") or 0)
            size, bitrate, fmt_hint = _parse_kuwo_minfo(row.get("MINFO") or "")
            dl_url, ext, dl_size, dl_bitrate = _kuwo_pick_download_url(rid)
            ext = ext or fmt_hint
            cover = row.get("hts_MVPIC") or row.get("web_albumpic_short") or ""
            if cover and not cover.startswith("http"):
                cover = "http://" + cover.lstrip("/")
            results.append(OnlineSong(
                source="kuwo",
                song_id=rid,
                title=title,
                artist=artist,
                album=album,
                filename=f"{_clean_filename(title)} - {_clean_filename(artist)}.{ext}",
                url=dl_url,
                lyric_url=f"http://m.kuwo.cn/newh5/singles/songinfoandlrc?musicId={rid}",
                cover_url=cover,
                size=dl_size or size,
                format=ext,
                duration=duration,
                bitrate=dl_bitrate or bitrate,
                disabled=not bool(dl_url),
            ))
        except Exception as e:
            logger.debug(f"[online:kuwo] skip item: {e}")
    return results


def _kuwo_pick_download_url(rid: str) -> tuple[str, str, int, int]:
    random_id = f"C_APK_guanwang_{time.time_ns()}{random.randint(0, 999999)}"
    for br, ext, bitrate in (("2000kflac", "flac", 2000), ("flac", "flac", 1000), ("320kmp3", "mp3", 320), ("128kmp3", "mp3", 128)):
        try:
            resp = _SESSION.get(
                "https://mobi.kuwo.cn/mobi.s",
                params={
                    "f": "web",
                    "source": "kwplayercar_ar_6.0.0.9_B_jiakong_vh.apk",
                    "from": "PC",
                    "type": "convert_url_with_sign",
                    "br": br,
                    "rid": rid,
                    "user": random_id,
                },
                timeout=15,
            ).json()
            url = ((resp.get("data") or {}).get("url") or "").strip()
            if url:
                if not url.startswith("http"):
                    url = "https:" + url if url.startswith("//") else url
                return url, ext, _head_size(url), bitrate
        except Exception:
            continue
    try:
        resp = _SESSION.get(
            "http://www.kuwo.cn/api/v1/www/music/playUrl",
            params={"mid": rid, "type": "music", "httpsStatus": 1},
            headers={"Secret": "kuwo_web_secret", "Cookie": "kw_token=secret_token"},
            timeout=15,
        ).json()
        url = ((resp.get("data") or {}).get("url") or "").strip()
        if url:
            ext = "flac" if ".flac" in url.lower() else "mp3"
            return url, ext, _head_size(url), 0
    except Exception:
        pass
    return "", "mp3", 0, 0


def _nki_api_key() -> str:
    try:
        site = (config.sites or {}).get("nki")
        if site and site.api_key:
            return site.api_key
    except Exception:
        pass
    return os.environ.get("ONLINE_MUSIC_NKI_APIKEY", "")


def _nki_pick_qq_download_url(song_mid: str, timeout: float | tuple[float, float] = (3, 8), attempts: int = 3) -> tuple[str, str, int, int, dict]:
    """Resolve QQ songmid through user-configured NKI open API.

    Returns best available quality as (url, ext, size, bitrate, raw_metadata).
    NKI is the best QQ resolver here, but the endpoint is occasionally unstable
    (SSL EOF / read timeout). Use short bounded retries with fresh connections so
    one transient failure does not surface to the user as a random download error.
    """
    api_key = _nki_api_key()
    if not api_key or not song_mid:
        return "", "", 0, 0, {}
    started = time.perf_counter()
    data = None
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            resp = requests.get(
                "https://api.nki.pw/API/music_open_api.php",
                params={"mid": song_mid, "apikey": api_key},
                headers={
                    "User-Agent": _SESSION.headers.get("User-Agent", "Mozilla/5.0"),
                    "Accept": "application/json,text/plain,*/*",
                    "Connection": "close",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"[online:nki] resolved {song_mid} in {time.perf_counter() - started:.2f}s attempt={attempt}")
            break
        except Exception as e:
            last_error = e
            logger.warning(f"[online:nki] resolve attempt {attempt}/{attempts} failed for {song_mid}: {e}")
            if attempt < attempts:
                time.sleep(0.4 * attempt)
    if data is None:
        logger.warning(f"[online:nki] resolve failed for {song_mid} after {time.perf_counter() - started:.2f}s: {last_error}")
        return "", "", 0, 0, {}

    # Prefer lossless SQ, then high quality, then standard.
    for suffix, ext in (("sq", "flac"), ("pq", "flac"), ("hq", "m4a"), ("standard", "m4a"), ("fq", "m4a")):
        url_key = "song_play_url" if suffix == "" else f"song_play_url_{suffix}"
        size_key = "song_size_str" if suffix == "" else f"song_size_{suffix}_str"
        kbps_key = "kbps" if suffix == "" else f"kbps_{suffix}"
        filename_key = "song_filename" if suffix == "" else ("song_filename_lq" if suffix == "standard" else f"song_filename_{suffix}")
        url = (data.get(url_key) or "").strip()
        if not url:
            continue
        filename = str(data.get(filename_key) or "").lower()
        inferred_ext = "flac" if filename.endswith(".flac") or ".flac" in url.lower() else ext
        try:
            size = int(data.get(size_key) or 0)
        except Exception:
            size = 0
        try:
            bitrate = int(data.get(kbps_key) or 0)
        except Exception:
            bitrate = 0
        return url, inferred_ext, size, bitrate, data

    # Some responses expose the default fields without a suffix.
    url = (data.get("song_play_url") or "").strip()
    if url:
        try:
            size = int(data.get("song_size_str") or 0)
        except Exception:
            size = 0
        try:
            bitrate = int(data.get("kbps") or 0)
        except Exception:
            bitrate = 0
        filename = str(data.get("song_filename") or "").lower()
        ext = "flac" if filename.endswith(".flac") or ".flac" in url.lower() else "m4a"
        return url, ext, size, bitrate, data
    return "", "", 0, 0, data


def search_qq(keyword: str, limit: int = 20) -> list[OnlineSong]:
    """Search QQ Music. 参考 music-lib qq: 先 search_for_qq_cp 拿 songmid，再 musicu.fcg 拿 vkey。

    依次尝试质量档位 (FLAC → 320k → 128k)，不带 cookie 拿不到 VIP 资源、会静默回落。
    """
    try:
        resp = _SESSION.get(
            "https://c.y.qq.com/soso/fcgi-bin/search_for_qq_cp",
            params={"w": keyword, "format": "json", "p": 1, "n": limit, "new_json": 1},
            headers={"Referer": "https://y.qq.com/"},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        logger.warning(f"[online:qq] search failed: {e}")
        return []

    rows = ((data.get("data") or {}).get("song") or {}).get("list") or []
    if not rows:
        return []

    results: list[OnlineSong] = []
    for row in rows[:limit]:
        try:
            song_mid = row.get("songmid") or row.get("mid") or ""
            if not song_mid:
                continue
            # 跳过付费不免费试听的资源（拿到也只能下 30s 试听片段）
            pay = row.get("pay") or {}
            paydownload = int(pay.get("paydownload") or 0)
            title = row.get("songname") or row.get("name") or row.get("title") or ""
            album = row.get("albumname") or ""
            album_mid = row.get("albummid") or ""
            singers = row.get("singer") or []
            artist = "/".join(s.get("name", "") for s in singers if s.get("name"))
            cover = (
                f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{album_mid}.jpg"
                if album_mid
                else ""
            )
            # Search must stay fast: only collect metadata here.  QQ download
            # URLs (NKI first, then musicu.fcg fallback) are resolved on click in
            # download_online_song(), because NKI can take 20s+ or timeout.
            size = int(row.get("sizeflac") or row.get("size320") or row.get("size128") or 0)
            ext = "flac" if int(row.get("sizeflac") or 0) > 0 else "mp3"
            bitrate = 0
            url = ""
            disabled = False
            results.append(OnlineSong(
                source="qq",
                song_id=song_mid,
                title=title,
                artist=artist,
                album=album,
                filename=f"{_clean_filename(title)} - {_clean_filename(artist)}.{ext}",
                url=url,
                lyric_url=f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={song_mid}&format=json&nobase64=1&g_tk=5381",
                cover_url=cover,
                size=size or int(row.get("size128") or 0),
                format=ext,
                duration=int(row.get("interval") or row.get("duration") or 0),
                bitrate=bitrate,
                disabled=disabled,
            ))
        except Exception as e:
            logger.debug(f"[online:qq] skip item: {e}")
    return results


def _qq_pick_download_url(song_mid: str) -> tuple[str, str, int]:
    """调 musicu.fcg 拿 vkey，按 FLAC>320k>128k 返回首个可用链接。

    参考 music-lib/qq/download.go: 预生成 filename 列表，哪个 midurlinfo 返回了 purl 就走哪个。
    """
    import json
    import random
    guid = f"{random.randint(1000000000, 9999999999)}"
    # Non-VIP 只能拿 320k/128k mp3。VIP 资源需要 cookie，暂不实现。
    quality_map = [
        ("F000", "flac"),
        ("M800", "mp3"),
        ("M500", "mp3"),
    ]
    filenames = [f"{p}{song_mid}{song_mid}.{ext}" for p, ext in quality_map]
    payload = {
        "comm": {
            "cv": 4747474,
            "ct": 24,
            "format": "json",
            "inCharset": "utf-8",
            "outCharset": "utf-8",
            "notice": 0,
            "platform": "yqq.json",
            "needNewCode": 1,
            "uin": 0,
        },
        "req_1": {
            "module": "music.vkey.GetVkey",
            "method": "UrlGetVkey",
            "param": {
                "guid": guid,
                "songmid": [song_mid] * len(filenames),
                "songtype": [0] * len(filenames),
                "uin": "0",
                "loginflag": 1,
                "platform": "20",
                "filename": filenames,
            },
        },
    }
    try:
        resp = _SESSION.post(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            data=json.dumps(payload),
            headers={
                "Referer": "https://y.qq.com/",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        logger.debug(f"[online:qq] vkey fetch failed: {e}")
        return "", "mp3", 0

    mid_url_info = ((data.get("req_1") or {}).get("data") or {}).get("midurlinfo") or []
    purl_by_filename = {item.get("filename", ""): item.get("purl", "") for item in mid_url_info}
    file_size_by_filename = {item.get("filename", ""): int(item.get("filesize") or 0) for item in mid_url_info}
    for filename, ext in zip(filenames, [e for _, e in quality_map]):
        purl = purl_by_filename.get(filename) or ""
        if purl:
            return f"https://ws.stream.qqmusic.qq.com/{purl}", ext, file_size_by_filename.get(filename, 0)
    return "", "mp3", 0


def search_online(keyword: str, sources: list[str] | None = None, limit: int = 20) -> list[dict]:
    sources = list(dict.fromkeys(sources or ["qq", "migu", "kugou", "netease"]))
    results: list[OnlineSong] = []
    if not sources:
        return []

    # The old path used `limit` per source sequentially, so a 30-result search
    # across 5 sources could trigger ~100 network requests before the UI updated.
    # Keep enough candidates per source, but cap fan-out and run sources in
    # parallel so slow providers no longer block every other result.
    per_source = max(3, min(20, math.ceil(limit / len(sources)) + 2))
    source_funcs = {
        "migu": search_migu,
        "kugou": search_kugou,
        "netease": search_netease,
        "qq": search_qq,
        "kuwo": search_kuwo,
    }

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(len(sources), 5)) as pool:
        futures = {}
        for src in sources:
            fn = source_funcs.get(src)
            if not fn:
                continue
            futures[pool.submit(fn, keyword, per_source)] = src
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                rows = fut.result()
                logger.info(f"[online:{src}] search returned {len(rows)} rows; aggregate elapsed={time.perf_counter() - started:.2f}s")
                results.extend(rows)
            except Exception as e:
                logger.warning(f"[online:{src}] search failed: {e}")

    # Prefer enabled/downloadable first, then larger files.
    results.sort(key=lambda x: (x.disabled, -(x.size or 0)))
    logger.info(f"[online] search keyword={keyword!r} sources={sources} per_source={per_source} total={len(results)} elapsed={time.perf_counter() - started:.2f}s")
    return [r.to_dict() for r in results[:limit]]


def _download_headers_for_song(song: dict) -> dict:
    """Headers that make direct music CDN downloads less likely to be rejected."""
    headers = {"User-Agent": "Mozilla/5.0"}
    source = song.get("source") or ""
    if source == "qq":
        headers.update({
            "Referer": "https://y.qq.com/",
            "Origin": "https://y.qq.com",
        })
    elif source == "netease":
        headers.update({"Referer": "https://music.163.com/"})
    elif source == "kuwo":
        headers.update({"Referer": "https://www.kuwo.cn/"})
    return headers


def _unique_target(target_dir: Path, filename: str) -> Path:
    target = target_dir / filename
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    i = 1
    while target.exists():
        target = target_dir / f"{stem}({i}){suffix}"
        i += 1
    return target


def _qq_download_candidates(song: dict) -> list[tuple[str, str]]:
    """Return QQ download candidates as (url, ext), including fresh fallback URLs.

    QQ CDN vkeys expire and cached/search-time URLs can start returning 418.
    User-configured NKI is the first priority, then built-in musicu.fcg, then
    any original URL carried by older search results as a last-resort fallback.
    """
    candidates: list[tuple[str, str]] = []
    original_url = song.get("url") or ""
    original_ext = song.get("format") or "mp3"

    song_mid = song.get("song_id") or ""
    if song_mid:
        # User-provided NKI API is the preferred QQ downloader.  Built-in vkey
        # is only a fallback for free tracks / API failures.
        try:
            url, ext, _size, _bitrate, _meta = _nki_pick_qq_download_url(song_mid)
            if url and all(url != u for u, _ in candidates):
                candidates.append((url, ext or original_ext or "mp3"))
        except Exception as e:
            logger.debug(f"[online:qq] nki fallback resolve failed: {e}")
        try:
            url, ext, _size = _qq_pick_download_url(song_mid)
            if url and all(url != u for u, _ in candidates):
                candidates.append((url, ext or "mp3"))
        except Exception as e:
            logger.debug(f"[online:qq] builtin fallback resolve failed: {e}")

    if original_url and all(original_url != u for u, _ in candidates):
        candidates.append((original_url, original_ext))
    return candidates


def resolve_online_song(song: dict) -> dict:
    """Resolve downloadable candidates without downloading the file."""
    source = song.get("source") or "online"
    if source == "qq":
        candidates = _qq_download_candidates(song)
    else:
        url = song.get("url") or ""
        candidates = [(url, song.get("format") or Path(song.get("filename") or "").suffix.lstrip(".") or "mp3")] if url else []
    items = []
    for idx, (candidate_url, ext) in enumerate(candidates, start=1):
        parsed = urlparse(candidate_url)
        items.append({
            "index": idx,
            "format": ext or "",
            "host": parsed.netloc,
            "scheme": parsed.scheme,
            "path_ext": Path(parsed.path).suffix.lstrip("."),
            "url_preview": f"{parsed.scheme}://{parsed.netloc}{parsed.path[:48]}" if parsed.scheme and parsed.netloc else "",
        })
    return {"ok": bool(items), "source": source, "song_id": song.get("song_id") or "", "candidate_count": len(items), "candidates": items}


def download_online_song(song: dict) -> str:
    """Download an online song to config.paths.downloads/online and return file path."""
    url = song.get("url") or ""
    source = song.get("source") or "online"
    if not url and source != "qq":
        raise OnlineDownloadError("没有可下载链接", reason="no_download_url", source=source)
    filename = _clean_filename(song.get("filename") or f"{song.get('title','unknown')} - {song.get('artist','unknown')}.{song.get('format','mp3')}")
    target_dir = Path(config.paths.downloads) / "online"
    target_dir.mkdir(parents=True, exist_ok=True)

    if source == "qq":
        candidates = _qq_download_candidates(song)
    else:
        candidates = [(url, song.get("format") or Path(filename).suffix.lstrip(".") or "mp3")]

    if not candidates:
        reason = "qq_resolve_failed" if source == "qq" else "no_download_url"
        raise OnlineDownloadError("解析失败：没有拿到可下载链接", reason=reason, source=source, details={"song_id": song.get("song_id") or ""})

    headers = _download_headers_for_song(song)
    last_error: Exception | None = None
    failures = []
    for idx, (candidate_url, ext) in enumerate(candidates, start=1):
        candidate_filename = filename
        if ext:
            current_suffix = Path(candidate_filename).suffix.lower().lstrip(".")
            if current_suffix and current_suffix != ext.lower():
                candidate_filename = str(Path(candidate_filename).with_suffix(f".{ext}"))
            elif not current_suffix:
                candidate_filename = f"{candidate_filename}.{ext}"

        for attempt in range(1, 3):
            target = _unique_target(target_dir, candidate_filename)
            logger.info(f"[online:{source}] Downloading {candidate_filename} (candidate {idx}/{len(candidates)}, attempt {attempt}/2)")
            try:
                bytes_written = 0
                content_type = ""
                with _SESSION.get(candidate_url, stream=True, timeout=(10, 90), headers=headers) as resp:
                    resp.raise_for_status()
                    content_type = (resp.headers.get("content-type") or "").lower()
                    if "text/html" in content_type or "application/json" in content_type:
                        raise RuntimeError(f"下载地址返回非音频内容: {content_type}")
                    with open(target, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                bytes_written += len(chunk)
                                f.write(chunk)
                if bytes_written < 4096:
                    raise RuntimeError(f"下载内容过小: {bytes_written} bytes")
                logger.info(f"[online:{source}] Downloaded {candidate_filename}: {bytes_written} bytes type={content_type or '-'}")
                break
            except Exception as e:
                last_error = e
                failures.append({"candidate": idx, "attempt": attempt, "error": str(e)[:300]})
                try:
                    if target.exists():
                        target.unlink()
                except Exception:
                    pass
                logger.warning(f"[online:{source}] download candidate {idx}/{len(candidates)} attempt {attempt}/2 failed: {e}")
                if attempt < 2:
                    time.sleep(0.5 * attempt)
        else:
            continue
        break
    else:
        reason = "qq_download_failed" if source == "qq" else "download_failed"
        raise OnlineDownloadError(
            f"下载失败，所有候选链接均不可用: {last_error}",
            reason=reason,
            source=source,
            details={"song_id": song.get("song_id") or "", "candidate_count": len(candidates), "failures": failures[-6:]},
        )

    # Save source-provided lyrics if available. Pipeline scraping may improve/overwrite later.
    lyric_url = song.get("lyric_url") or ""
    if lyric_url:
        try:
            lyric_text = _SESSION.get(lyric_url, timeout=15, headers=headers).text
            if lyric_text and len(lyric_text) > 20:
                target.with_suffix(".lrc").write_text(lyric_text, encoding="utf-8")
        except Exception as e:
            logger.debug(f"[online:{source}] lyric download failed: {e}")

    return str(target)
