"""Discover API - local library recommendations and playlist import helpers."""
import logging
import random
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MusicFile

router = APIRouter()
logger = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://y.qq.com/",
})


def _norm_text(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def _song_fingerprint(title: str | None, artist: str | None = "") -> str:
    return f"{_norm_text(title)}::{_norm_text((artist or '').split('/')[0])}"


def _local_cover_url(artist: str, album: str) -> str:
    if not artist or not album:
        return ""
    return "/api/library/album-cover?" + urlencode({"artist": artist, "album": album})


def _local_song_item(row: MusicFile, reason: str) -> dict:
    artist = row.album_artist or row.artist or "未知艺人"
    album = row.album or "单曲/未知专辑"
    title = row.title or (Path(row.file_path).stem if row.file_path else "未知歌曲")
    return {
        "source": "local",
        "song_id": str(row.id),
        "file_id": row.id,
        "title": title,
        "artist": artist,
        "album": album,
        "cover": _local_cover_url(artist, album),
        "reason": reason,
        "in_library": True,
        "actions": [],
        "format": row.format or "",
        "duration": row.duration or 0,
        "bitrate": row.bitrate or 0,
    }


@router.get("/personalized")
def get_personalized(
    limit: int = Query(16, ge=4, le=40),
    seed: str | None = Query(None, description="Optional shuffle seed used by the Discover refresh button"),
    db: Session = Depends(get_db),
):
    """Pure local discovery recommendations from the user's own library only.

    This endpoint intentionally does not call external music recommendation APIs.
    It builds several local pools first, then shuffles the merged candidates with
    the supplied seed so the Discover refresh button actually returns a new batch
    instead of being dominated by the same recent/high-frequency tracks.
    """
    limit = max(4, min(int(limit or 16), 40))
    rng = random.Random(str(seed) if seed else None)
    rows = db.query(MusicFile).order_by(MusicFile.created_at.desc()).all()
    if not rows:
        return {"source": "local", "items": [], "message": "本地音乐库为空，暂无本地推荐"}

    artist_counts = Counter((r.album_artist or r.artist or "").strip() for r in rows)
    candidates: list[tuple[MusicFile, str, float]] = []
    recent_window = max(24, limit * 4)

    # 1) 最近入库池：仍然保留“今天听点新入库”的首页语义，但不固定排在最前。
    for idx, row in enumerate(rows[:recent_window]):
        freshness = max(0.0, 1.0 - idx / max(1, recent_window))
        candidates.append((row, "最近入库", 2.4 + freshness))

    # 2) 高频艺人池：同一高频艺人随机抽几首，而不是永远第一首。
    for artist, count in artist_counts.most_common(12):
        if not artist or artist.lower() in {"unknown artist", "未知艺人"}:
            continue
        artist_rows = [r for r in rows if (r.album_artist or r.artist or "").strip() == artist]
        rng.shuffle(artist_rows)
        for row in artist_rows[:2]:
            candidates.append((row, f"本地库高频艺人：{artist}（{count} 首）", 1.8 + min(count, 50) / 50))

    # 3) 随机发现池：全库参与，保证每次“换一批”明显变化。
    random_rows = rows[:]
    rng.shuffle(random_rows)
    for row in random_rows[: max(limit * 5, 40)]:
        candidates.append((row, "本地随机发现", 1.0))

    # 加权随机排序。权重影响入选概率，但最终顺序不再固定。
    rng.shuffle(candidates)
    candidates.sort(key=lambda item: rng.random() * max(item[2], 0.1), reverse=True)

    results: list[dict] = []
    seen: set[str] = set()

    def add_row(row: MusicFile, reason: str) -> None:
        if len(results) >= limit:
            return
        title = row.title or (Path(row.file_path).stem if row.file_path else "未知歌曲")
        fp = _song_fingerprint(title, row.artist or row.album_artist or "")
        if fp in seen:
            return
        seen.add(fp)
        results.append(_local_song_item(row, reason))

    for row, reason, _weight in candidates:
        add_row(row, reason)
        if len(results) >= limit:
            break

    # 极小曲库兜底：去重后不够时放宽指纹，至少返回可播项。
    if len(results) < min(limit, len(rows)):
        for row in random_rows:
            add_row(row, "本地随机发现")
            if len(results) >= limit:
                break

    return {"source": "local", "seed": seed, "items": results[:limit]}


def _resolve_qq_short_url(url: str) -> str:
    """Follow QQ Music short URL redirects and return final URL."""
    try:
        resp = _session.get(url, allow_redirects=True, timeout=10)
        return resp.url
    except Exception:
        return url

@router.post("/parse-playlist-url")
def parse_playlist_url(url: str = ""):
    """Parse a QQ Music or NetEase playlist URL and return song list."""
    import re
    import json as _json

    if not url:
        return {"ok": False, "message": "请输入歌单链接"}

    songs = []
    title = ""
    source = ""

    # QQ Music short URL (c6.y.qq.com/base/fcgi-bin/u?__=XXX) → resolve redirect
    if "c6.y.qq.com" in url or ("__=" in url and "y.qq.com" in url):
        resolved = _resolve_qq_short_url(url)
        logger.info(f"QQ short URL resolved: {url} → {resolved}")
        url = resolved

    # QQ Music: y.qq.com/n/ryqq/playlist/XXXXXXX or any URL with ?id= or playlist=
    # Also handles resolved short URLs like i.y.qq.com/n2/m/share/details/taoge.html?id=9220096531
    qq_match = re.search(r"playlist[/=](\d+)", url) or re.search(r"[?&]id=(\d+)", url)
    if not qq_match and ("y.qq.com" in url or "qq.com" in url):
        qq_match = re.search(r"(\d{10,})", url)  # fallback: any 10+ digit number
    if qq_match:
        pid = qq_match.group(1)
        try:
            # First fetch: get title + total song count from dirinfo
            resp = _session.get(
                "https://u.y.qq.com/cgi-bin/musicu.fcg",
                params={
                    "data": _json.dumps({"detail": {"module": "music.srfDissInfo.DissInfo", "method": "CgiGetDiss", "param": {"disstid": int(pid), "onlysonglist": 0, "song_num": 1, "song_begin": 0}}})
                },
                timeout=15,
            )
            data = resp.json()
            detail = data.get("detail", {}).get("data", {})
            dirinfo = detail.get("dirinfo", {})
            title = dirinfo.get("title", "") or ""
            total = dirinfo.get("songnum", 100) or 100
            source = "qqmusic"

            # Fetch all songs in one request (QQ Music API supports song_num up to total)
            resp2 = _session.get(
                "https://u.y.qq.com/cgi-bin/musicu.fcg",
                params={
                    "data": _json.dumps({"detail": {"module": "music.srfDissInfo.DissInfo", "method": "CgiGetDiss", "param": {"disstid": int(pid), "onlysonglist": 0, "song_num": min(total, 2000), "song_begin": 0}}})
                },
                timeout=30,
            )
            data2 = resp2.json()
            detail2 = data2.get("detail", {}).get("data", {})
            for s in detail2.get("songlist", []):
                singers = s.get("singer", [])
                artist = "/".join(x.get("name", "") for x in singers) if singers else ""
                songs.append({"title": s.get("name", ""), "artist": artist})
        except Exception as e:
            logger.warning(f"QQ playlist parse failed: {e}")

    # NetEase playlist: music.163.com/playlist?id=XXXXXXX or #/playlist?id=
    if not songs:
        import json as _json
        ne_match = re.search(r"(?:playlist[?/].*id=|playlist/)(\d+)", url)
        if ne_match or "163.com" in url:
            pid = ne_match.group(1) if ne_match else re.search(r"(\d{6,})", url)
            if pid:
                pid_str = pid if isinstance(pid, str) else pid.group(1)
                try:
                    # Use v6 endpoint to get all trackIds (old /api/playlist/detail only returns first page)
                    resp = _session.get(
                        "https://music.163.com/api/v6/playlist/detail",
                        params={"id": pid_str},
                        headers={"Referer": "https://music.163.com/"},
                        timeout=15,
                    )
                    data = resp.json()
                    playlist = data.get("playlist", {})
                    title = playlist.get("name", "")
                    source = "netease"

                    # Get full track list from /api/song/detail (batched 20 at a time)
                    track_ids = [t["id"] for t in playlist.get("trackIds", [])]
                    if not track_ids:
                        # Fallback: use tracks embedded in v6 response (usually first 10)
                        track_ids = [t["id"] for t in playlist.get("tracks", [])]

                    BATCH = 20
                    for i in range(0, len(track_ids), BATCH):
                        batch_ids = track_ids[i:i+BATCH]
                        try:
                            song_resp = _session.post(
                                "https://music.163.com/api/song/detail",
                                data={"ids": _json.dumps(batch_ids)},
                                headers={
                                    "Referer": "https://music.163.com/",
                                    "Content-Type": "application/x-www-form-urlencoded",
                                },
                                timeout=15,
                            )
                            song_data = song_resp.json()
                            for t in song_data.get("songs", []):
                                artists = t.get("artists", [])
                                artist = "/".join(a.get("name", "") for a in artists) if artists else ""
                                songs.append({"title": t.get("name", ""), "artist": artist})
                        except Exception as e:
                            logger.warning(f"NetEase song detail batch failed: {e}")
                except Exception as e:
                    logger.warning(f"NetEase playlist parse failed: {e}")

    if not songs:
        return {"ok": False, "message": "无法解析该链接，请确认是 QQ音乐 或 网易云 歌单链接"}

    return {
        "ok": True,
        "source": source,
        "title": title,
        "songs": songs,
        "count": len(songs),
    }

