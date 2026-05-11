"""Discover API - fetch recommendations from QQ Music / NetEase."""
import logging
import requests
from fastapi import APIRouter

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
    # QQ Music new songs API
    try:
        resp = _session.get(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            params={
                "data": '{"new_song":{"module":"newsong.NewSongServer","method":"get_new_song_info","param":{"type":5}}}'
            },
            timeout=10,
        )
        data = resp.json()
        songs = data.get("new_song", {}).get("data", {}).get("songlist", [])
        results = []
        for s in songs[:12]:
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


@router.get("/toplist")
def get_toplist():
    """Get music chart/ranking."""
    # QQ Music top list (热歌榜)
    try:
        resp = _session.get(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            params={
                "data": '{"toplist":{"module":"musicToplist.ToplistInfoServer","method":"GetDetail","param":{"topid":26,"num":20,"period":""}}}'
            },
            timeout=10,
        )
        data = resp.json()
        songs = data.get("toplist", {}).get("data", {}).get("songInfoList", [])
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
        return {"source": "qqmusic", "items": results}
    except Exception as e:
        logger.warning(f"QQ Music toplist failed: {e}")

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
