"""Discover API - fetch recommendations from QQ Music / NetEase."""
import logging
import random
import requests
from fastapi import APIRouter, Query

router = APIRouter()
logger = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://y.qq.com/",
})


@router.get("/recommend")
def get_recommendations():
    """Get personalized/hot song recommendations."""
    # QQ Music new songs API (type=0 for all regions, updates more frequently)
    try:
        resp = _session.get(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            params={
                "data": '{"new_song":{"module":"newsong.NewSongServer","method":"get_new_song_info","param":{"type":0}}}'
            },
            timeout=10,
        )
        data = resp.json()
        songs = data.get("new_song", {}).get("data", {}).get("songlist", [])
        # Shuffle and pick 12 random songs so each refresh feels different
        if len(songs) > 12:
            songs = random.sample(songs, 12)
        else:
            songs = songs[:12]
        results = []
        for s in songs:
            singers = s.get("singer", [])
            artist = "/".join(x.get("name", "") for x in singers) if singers else ""
            album = s.get("album", {})
            mid = album.get("mid", "")
            results.append({
                "title": s.get("name", ""),
                "artist": artist,
                "album": album.get("name", ""),
                "cover": f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{mid}.jpg" if mid else "",
            })
        return {"source": "qqmusic", "items": results}
    except Exception as e:
        logger.warning(f"QQ Music recommend failed: {e}")

    # Fallback: NetEase top songs
    try:
        resp = _session.get(
            "https://music.163.com/api/discovery/newSong",
            params={"areaId": 0, "limit": 12},
            headers={"Referer": "https://music.163.com/"},
            timeout=10,
        )
        data = resp.json()
        songs = data.get("data", [])
        results = []
        for s in songs[:12]:
            artists = s.get("artists", [])
            artist = "/".join(a.get("name", "") for a in artists) if artists else ""
            album = s.get("album", {})
            results.append({
                "title": s.get("name", ""),
                "artist": artist,
                "album": album.get("name", ""),
                "cover": album.get("picUrl", ""),
            })
        return {"source": "netease", "items": results}
    except Exception as e:
        logger.warning(f"NetEase recommend failed: {e}")
        return {"source": "none", "items": []}


@router.get("/playlists")
def get_playlists():
    """Get recommended playlists."""
    # QQ Music playlist recommendations
    try:
        resp = _session.get(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            params={
                "data": '{"recomPlaylist":{"module":"playlist.HotRecommendServer","method":"get_hot_recommend","param":{"async":1,"cmd":2}}}'
            },
            timeout=10,
        )
        data = resp.json()
        playlists = data.get("recomPlaylist", {}).get("data", {}).get("v_hot", [])
        results = []
        for p in playlists[:8]:
            results.append({
                "id": str(p.get("content_id", "")),
                "title": p.get("title", ""),
                "cover": p.get("cover", ""),
                "play_count": p.get("listen_num", 0),
            })
        return {"source": "qqmusic", "items": results}
    except Exception as e:
        logger.warning(f"QQ Music playlists failed: {e}")

    # Fallback NetEase
    try:
        resp = _session.get(
            "https://music.163.com/api/personalized/playlist",
            params={"limit": 8},
            headers={"Referer": "https://music.163.com/"},
            timeout=10,
        )
        data = resp.json()
        results = []
        for p in data.get("result", [])[:8]:
            results.append({
                "id": str(p.get("id", "")),
                "title": p.get("name", ""),
                "cover": p.get("picUrl", ""),
                "play_count": p.get("playCount", 0),
            })
        return {"source": "netease", "items": results}
    except Exception as e:
        logger.warning(f"NetEase playlists failed: {e}")
        return {"source": "none", "items": []}


@router.get("/playlist/{playlist_id}")
def get_playlist_detail(playlist_id: str, limit: int = Query(30, ge=1, le=200)):
    """Get playlist detail with song list."""
    # QQ Music playlist detail
    try:
        import json as _json
        resp = _session.get(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            params={
                "data": _json.dumps({"detail": {"module": "music.srfDissInfo.DissInfo", "method": "CgiGetDiss", "param": {"disstid": int(playlist_id), "onlysonglist": 0, "song_num": limit, "song_begin": 0}}})
            },
            timeout=10,
        )
        data = resp.json()
        detail = data.get("detail", {}).get("data", {})
        dirinfo = detail.get("dirinfo", {})
        songs = detail.get("songlist", [])
        results = []
        for s in songs:
            singers = s.get("singer", [])
            artist = "/".join(x.get("name", "") for x in singers) if singers else ""
            album = s.get("album", {})
            mid = album.get("mid", "") if isinstance(album, dict) else ""
            results.append({
                "title": s.get("name", ""),
                "artist": artist,
                "album": album.get("name", "") if isinstance(album, dict) else "",
                "cover": f"https://y.gtimg.cn/music/photo_new/T002R150x150M000{mid}.jpg" if mid else "",
            })
        return {
            "source": "qqmusic",
            "title": dirinfo.get("title", ""),
            "cover": dirinfo.get("picurl", ""),
            "desc": dirinfo.get("desc", ""),
            "songs": results,
        }
    except Exception as e:
        logger.warning(f"QQ Music playlist detail failed: {e}")

    # Fallback NetEase
    try:
        resp = _session.get(
            "https://music.163.com/api/playlist/detail",
            params={"id": playlist_id},
            headers={"Referer": "https://music.163.com/"},
            timeout=10,
        )
        data = resp.json()
        result = data.get("result", {})
        tracks = result.get("tracks", [])
        results = []
        for t in tracks[:limit]:
            artists = t.get("artists", [])
            artist = "/".join(a.get("name", "") for a in artists) if artists else ""
            album = t.get("album", {})
            results.append({
                "title": t.get("name", ""),
                "artist": artist,
                "album": album.get("name", ""),
                "cover": album.get("picUrl", "") + "?param=150y150" if album.get("picUrl") else "",
            })
        return {
            "source": "netease",
            "title": result.get("name", ""),
            "cover": result.get("coverImgUrl", ""),
            "desc": result.get("description", ""),
            "songs": results,
        }
    except Exception as e:
        logger.warning(f"NetEase playlist detail failed: {e}")
        return {"source": "none", "title": "", "songs": []}


@router.get("/toplist")
def get_toplist():
    """Get music chart/ranking (daily updated)."""
    # QQ Music 飙升榜 (topid=62, daily update) with fallback to 热歌榜 (topid=26)
    for topid in (62, 26):
        try:
            resp = _session.get(
                "https://u.y.qq.com/cgi-bin/musicu.fcg",
                params={
                    "data": '{"toplist":{"module":"musicToplist.ToplistInfoServer","method":"GetDetail","param":{"topid":' + str(topid) + ',"num":50,"period":""}}}'
                },
                timeout=10,
            )
            data = resp.json()
            tl_data = data.get("toplist", {}).get("data", {})
            # Prefer data.data.song (richer, has cover) over songInfoList
            songs_rich = tl_data.get("data", {}).get("song", []) if isinstance(tl_data.get("data"), dict) else tl_data.get("song", [])
            if not songs_rich:
                songs_rich = tl_data.get("song", [])
            if songs_rich:
                results = []
                for s in songs_rich[:20]:
                    results.append({
                        "rank": s.get("rank", 0),
                        "title": s.get("title", ""),
                        "artist": s.get("singerName", ""),
                        "album": "",
                        "cover": s.get("cover", ""),
                    })
                return {"source": "qqmusic", "topid": topid, "period": tl_data.get("data", {}).get("period", "") if isinstance(tl_data.get("data"), dict) else tl_data.get("period", ""), "items": results}

            # Fallback: songInfoList (old format)
            songs = tl_data.get("songInfoList", [])
            if songs:
                results = []
                for i, s in enumerate(songs[:20], 1):
                    singers = s.get("singer", [])
                    artist = "/".join(x.get("name", "") for x in singers) if singers else ""
                    album = s.get("album", {})
                    mid = album.get("mid", "")
                    results.append({
                        "rank": i,
                        "title": s.get("name", ""),
                        "artist": artist,
                        "album": album.get("name", ""),
                        "cover": f"https://y.gtimg.cn/music/photo_new/T002R150x150M000{mid}.jpg" if mid else "",
                    })
                return {"source": "qqmusic", "topid": topid, "period": tl_data.get("period", ""), "items": results}
        except Exception as e:
            logger.warning(f"QQ Music toplist (topid={topid}) failed: {e}")
            continue

    # Fallback NetEase (飙升榜 id=19723756)
    try:
        resp = _session.get(
            "https://music.163.com/api/playlist/detail",
            params={"id": 19723756},
            headers={"Referer": "https://music.163.com/"},
            timeout=10,
        )
        data = resp.json()
        tracks = data.get("result", {}).get("tracks", [])
        results = []
        for i, t in enumerate(tracks[:20], 1):
            artists = t.get("artists", [])
            artist = "/".join(a.get("name", "") for a in artists) if artists else ""
            album = t.get("album", {})
            results.append({
                "rank": i,
                "title": t.get("name", ""),
                "artist": artist,
                "album": album.get("name", ""),
                "cover": album.get("picUrl", "") + "?param=150y150" if album.get("picUrl") else "",
            })
        return {"source": "netease", "items": results}
    except Exception as e:
        logger.warning(f"NetEase toplist failed: {e}")
        return {"source": "none", "items": []}


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

    # QQ Music playlist: y.qq.com/n/ryqq/playlist/XXXXXXX
    qq_match = re.search(r"playlist[/=](\d+)", url)
    if qq_match or "y.qq.com" in url or "qq.com" in url:
        playlist_id = qq_match.group(1) if qq_match else re.search(r"(\d{6,})", url)
        if playlist_id:
            pid = playlist_id if isinstance(playlist_id, str) else playlist_id.group(1)
            try:
                resp = _session.get(
                    "https://u.y.qq.com/cgi-bin/musicu.fcg",
                    params={
                        "data": _json.dumps({"detail": {"module": "music.srfDissInfo.DissInfo", "method": "CgiGetDiss", "param": {"disstid": int(pid), "onlysonglist": 0, "song_num": 50, "song_begin": 0}}})
                    },
                    timeout=15,
                )
                data = resp.json()
                detail = data.get("detail", {}).get("data", {})
                dirinfo = detail.get("dirinfo", {})
                title = dirinfo.get("title", "")
                source = "qqmusic"
                for s in detail.get("songlist", []):
                    singers = s.get("singer", [])
                    artist = "/".join(x.get("name", "") for x in singers) if singers else ""
                    songs.append({"title": s.get("name", ""), "artist": artist})
            except Exception as e:
                logger.warning(f"QQ playlist parse failed: {e}")

    # NetEase playlist: music.163.com/playlist?id=XXXXXXX or #/playlist?id=
    if not songs:
        ne_match = re.search(r"(?:playlist[?/].*id=|playlist/)(\d+)", url)
        if ne_match or "163.com" in url:
            pid = ne_match.group(1) if ne_match else re.search(r"(\d{6,})", url)
            if pid:
                pid_str = pid if isinstance(pid, str) else pid.group(1)
                try:
                    resp = _session.get(
                        "https://music.163.com/api/playlist/detail",
                        params={"id": pid_str},
                        headers={"Referer": "https://music.163.com/"},
                        timeout=15,
                    )
                    data = resp.json()
                    result = data.get("result", {})
                    title = result.get("name", "")
                    source = "netease"
                    for t in result.get("tracks", [])[:50]:
                        artists = t.get("artists", [])
                        artist = "/".join(a.get("name", "") for a in artists) if artists else ""
                        songs.append({"title": t.get("name", ""), "artist": artist})
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

