"""Assistant tool registry and implementations."""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

import app.config as cfg_module
from app.config import config
from app.version import APP_VERSION
from app.models import DownloadTask, MusicFile, Subscription
from app.services.searcher import search_with_chain, fetch_torrent_info_hash, download_torrent_content
from app.services.online_music import search_online, download_online_song as _download_online_song
from app.services.pipeline import _process_completed_torrent
from app.downloader.qbittorrent import qb_client


class ToolError(RuntimeError):
    pass


def _size_gb(value: float | int | None) -> float:
    return round(float(value or 0) / 1024 / 1024 / 1024, 2)


def get_system_status(db: Session, **kwargs) -> dict:
    return {
        "version": APP_VERSION,
        "sites_enabled": [name for name, site in config.sites.items() if site.enabled],
        "library_files": db.query(MusicFile).count(),
        "subscriptions": db.query(Subscription).count(),
        "tasks": db.query(DownloadTask).count(),
        "assistant_time": datetime.datetime.utcnow().isoformat() + "Z",
    }


def get_library_stats(db: Session, **kwargs) -> dict:
    rows = db.query(MusicFile).all()
    albums = {(r.album_artist or r.artist or "未知艺人", r.album or "未知专辑") for r in rows}
    formats: dict[str, int] = {}
    total_duration = 0.0
    for r in rows:
        if r.format:
            formats[r.format] = formats.get(r.format, 0) + 1
        total_duration += r.duration or 0
    return {
        "tracks": len(rows),
        "albums": len(albums),
        "formats": formats,
        "total_hours": round(total_duration / 3600, 1),
    }


def search_library(db: Session, keyword: str = "", limit: int = 10, **kwargs) -> dict:
    keyword = (keyword or "").strip()
    q = db.query(MusicFile)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (MusicFile.title.ilike(like)) |
            (MusicFile.artist.ilike(like)) |
            (MusicFile.album_artist.ilike(like)) |
            (MusicFile.album.ilike(like))
        )
    rows = q.order_by(MusicFile.created_at.desc()).limit(max(1, min(int(limit or 10), 30))).all()
    return {"items": [
        {
            "id": r.id,
            "title": r.title,
            "artist": r.artist,
            "album_artist": r.album_artist,
            "album": r.album,
            "format": r.format,
            "duration": r.duration,
            "file_path": r.file_path,
        }
        for r in rows
    ]}


def list_tasks(db: Session, limit: int = 10, **kwargs) -> dict:
    rows = db.query(DownloadTask).order_by(DownloadTask.created_at.desc()).limit(max(1, min(int(limit or 10), 30))).all()
    return {"items": [
        {
            "id": r.id,
            "name": r.torrent_name,
            "site": r.site,
            "status": r.status,
            "size_gb": _size_gb(r.size),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "hash": r.torrent_hash,
        }
        for r in rows
    ]}


def list_subscriptions(db: Session, limit: int = 20, **kwargs) -> dict:
    rows = db.query(Subscription).order_by(Subscription.created_at.desc()).limit(max(1, min(int(limit or 20), 50))).all()
    return {"items": [
        {
            "id": r.id,
            "keyword": r.keyword,
            "type": r.type,
            "quality": r.quality,
            "sites": r.sites,
            "enabled": r.enabled,
            "last_search_at": r.last_search_at.isoformat() if r.last_search_at else None,
        }
        for r in rows
    ]}


def search_pt(db: Session, keyword: str, sites: list[str] | None = None, limit: int = 10, **kwargs) -> dict:
    if not keyword:
        raise ToolError("缺少 keyword")
    resp = search_with_chain(keyword, sites=sites or None, limit=max(1, min(int(limit or 10), 30)))
    return {
        "queries": [q.keyword for q in resp.queries],
        "sites": [s.__dict__ for s in resp.sites],
        "items": [
            {
                "site": item.torrent.site,
                "torrent_id": item.torrent.torrent_id,
                "title": item.torrent.title,
                "size_gb": _size_gb(item.torrent.size),
                "seeders": item.torrent.seeders,
                "leechers": item.torrent.leechers,
                "free": item.torrent.free,
                "score": item.score,
                "quality": item.quality,
                "format": item.media_format,
                "reasons": item.reasons,
                "download_args": {
                    "site": item.torrent.site,
                    "torrent_id": item.torrent.torrent_id,
                    "title": item.torrent.title,
                },
            }
            for item in resp.results[:max(1, min(int(limit or 10), 30))]
        ],
        "instruction": "如果用户要下载某个结果，调用 download_torrent，并原样传入该结果的 download_args。",
    }


def search_online_tool(db: Session, keyword: str, sources: list[str] | None = None, limit: int = 10, **kwargs) -> dict:
    if not keyword:
        raise ToolError("缺少 keyword")
    items = search_online(keyword, sources=sources, limit=max(1, min(int(limit or 10), 20)))
    for item in items:
        item["download_args"] = {"song": item, "organize": True}
    return {"items": items, "instruction": "如果用户要下载某个结果，调用 download_online_song，并原样传入该结果的 download_args。"}


def search_download_candidates(db: Session, keyword: str, sites: list[str] | None = None, sources: list[str] | None = None, limit: int = 8, **kwargs) -> dict:
    """Search both PT torrents and online music candidates for download decisions."""
    if not keyword:
        raise ToolError("缺少 keyword")
    per_source_limit = max(1, min(int(limit or 8), 12))
    pt_error = ""
    online_error = ""
    try:
        pt = search_pt(db, keyword=keyword, sites=sites, limit=per_source_limit)
    except Exception as exc:
        pt = {"items": []}
        pt_error = str(exc)[:200]
    if getattr(cfg_module.config.assistant, "allow_online_search_candidates", True):
        try:
            online = search_online_tool(db, keyword=keyword, sources=sources, limit=per_source_limit)
        except Exception as exc:
            online = {"items": []}
            online_error = str(exc)[:200]
    else:
        online = {"items": []}
        online_error = "智能助手设置已关闭在线音乐候选。"
    return {
        "keyword": keyword,
        "pt": {"items": pt.get("items") or [], "error": pt_error},
        "online": {"items": online.get("items") or [], "error": online_error},
        "instruction": (
            "下载决策：专辑、合集、整轨、CUE、PT/做种/无损包优先使用 pt.items 的 download_args 调用 download_torrent；"
            "只有在线候选开关开启且 online.items 有结果时，单曲/快速下载才可考虑 online.items 的 download_args 调用 download_online_song。"
            "如果用户明确说直接下载，选择最匹配候选继续调用对应下载工具；否则推荐 1-3 个候选让用户选。"
        ),
    }


def pause_task(db: Session, task_id: int, **kwargs) -> dict:
    task = db.query(DownloadTask).filter(DownloadTask.id == int(task_id)).first()
    if not task:
        raise ToolError("任务不存在")
    if task.torrent_hash and not task.torrent_hash.startswith(("online:", "SIMULATED_")):
        qb_client.pause_torrent(task.torrent_hash)
    task.status = "paused"
    db.commit()
    return {"ok": True, "task_id": task.id, "status": task.status}


def resume_task(db: Session, task_id: int, **kwargs) -> dict:
    task = db.query(DownloadTask).filter(DownloadTask.id == int(task_id)).first()
    if not task:
        raise ToolError("任务不存在")
    if task.torrent_hash and not task.torrent_hash.startswith(("online:", "SIMULATED_")):
        qb_client.resume_torrent(task.torrent_hash)
    task.status = "downloading"
    db.commit()
    return {"ok": True, "task_id": task.id, "status": task.status}


def create_subscription(db: Session, keyword: str, type: str = "artist", quality: str = "any", sites: str = "all", enabled: bool = True, **kwargs) -> dict:
    keyword = (keyword or "").strip()
    if not keyword:
        raise ToolError("缺少订阅关键词")
    sub = Subscription(keyword=keyword, type=type or "artist", quality=quality or "any", sites=sites or "all", enabled=bool(enabled))
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"ok": True, "subscription": {"id": sub.id, "keyword": sub.keyword, "type": sub.type, "quality": sub.quality, "sites": sub.sites, "enabled": sub.enabled}}


def download_torrent(db: Session, site: str, torrent_id: str, title: str = "", **kwargs) -> dict:
    if not site or not torrent_id:
        raise ToolError("缺少 site 或 torrent_id")
    expected_hash, torrent_content = fetch_torrent_info_hash(site, torrent_id)
    if not expected_hash or not torrent_content:
        raise ToolError("种子下载失败，可能是站点 Cookie 过期或资源不可用")
    existing = db.query(DownloadTask).filter(DownloadTask.torrent_hash == expected_hash).first()
    if existing:
        return {"ok": True, "already_exists": True, "task_id": existing.id, "hash": expected_hash, "message": "任务已存在"}
    torrent_hash = download_torrent_content(torrent_content)
    if not torrent_hash:
        raise ToolError("添加到 qBittorrent 失败")
    task = DownloadTask(
        torrent_name=title or f"{site}:{torrent_id}",
        torrent_hash=torrent_hash.lower(),
        site=site,
        status="downloading",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"ok": True, "task_id": task.id, "hash": torrent_hash.lower(), "title": task.torrent_name}


def download_online_song(db: Session, song: dict, organize: bool = True, **kwargs) -> dict:
    import uuid
    if not song:
        raise ToolError("缺少可下载歌曲信息")
    # QQ search results intentionally omit URL so search stays fast; the lower
    # level downloader resolves NKI/QQ vkey candidates on click/tool execution.
    if not song.get("url") and song.get("source") != "qq":
        raise ToolError("缺少可下载歌曲链接")
    title = song.get("title") or song.get("filename") or "online-music"
    source = song.get("source") or "online"
    file_path = _download_online_song(song)
    synthetic_hash = f"online:{uuid.uuid4().hex}"
    task = DownloadTask(
        torrent_name=title,
        torrent_hash=synthetic_hash,
        site=source,
        size=float(song.get("size") or 0),
        status="downloaded",
        save_path=file_path,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if organize:
        _process_completed_torrent({
            "hash": synthetic_hash,
            "name": title,
            "content_path": file_path,
            "metadata": {
                "source": source,
                "song_id": song.get("song_id") or "",
                "title": song.get("title") or title,
                "artist": song.get("artist") or "",
                "album": song.get("album") or "",
                "duration": song.get("duration") or 0,
            },
        })
    return {"ok": True, "task_id": task.id, "file_path": file_path, "organized": organize}


def organize_task(db: Session, task_id: int, **kwargs) -> dict:
    task = db.query(DownloadTask).filter(DownloadTask.id == int(task_id)).first()
    if not task:
        raise ToolError("任务不存在")
    if not task.torrent_hash:
        raise ToolError("任务缺少 hash")
    if task.torrent_hash.startswith("online:"):
        content_path = task.save_path
    else:
        info = qb_client.get_torrents_by_hash([task.torrent_hash.lower()]).get(task.torrent_hash.lower())
        if not info:
            raise ToolError("qB 中找不到该任务")
        if (info.get("progress") or 0) < 1:
            raise ToolError("任务还没有下载完成")
        content_path = info.get("content_path") or info.get("save_path")
    if not content_path:
        raise ToolError("找不到任务文件路径")
    _process_completed_torrent({"hash": task.torrent_hash.lower(), "name": task.torrent_name, "content_path": content_path, "mark_processed": True})
    return {"ok": True, "task_id": task.id, "status": "organized"}


def rescrape_album(db: Session, artist: str, album: str, **kwargs) -> dict:
    artist = (artist or "").strip()
    album = (album or "").strip()
    if not artist or not album:
        raise ToolError("缺少 artist 或 album")
    from app.api.library import rescrape_albums
    return rescrape_albums({"albums": [{"artist": artist, "album": album}], "async": True}, db=db)


def complete_album(db: Session, artist: str, album: str, dry_run: bool = True, limit: int = 40, sources: list[str] | None = None, **kwargs) -> dict:
    """Preview or download missing tracks for a local album."""
    artist = (artist or "").strip()
    album = (album or "").strip()
    if not artist or not album:
        raise ToolError("缺少 artist 或 album")
    from app.api.library import complete_album as complete_album_api
    payload = {
        "artist": artist,
        "album": album,
        "dry_run": bool(dry_run),
        "limit": max(5, min(int(limit or 40), 80)),
    }
    if sources:
        payload["sources"] = sources
    return complete_album_api(payload, db=db)


def query_library_health(db: Session, kind: str = "", limit: int = 20, **kwargs) -> dict:
    """Query library hygiene issues for assistant diagnosis."""
    from app.api.library import library_health
    allowed = {"", "missing_cover", "missing_lyrics", "missing_duration", "unknown_artist", "unscraped", "cue_candidates", "album_artist_conflicts"}
    kind = (kind or "").strip()
    if kind not in allowed:
        raise ToolError("未知治理类别")
    return library_health(kind=kind, limit=max(1, min(int(limit or 20), 100)), db=db)


def read_recent_logs(db: Session, lines: int = 120, level: str = "", **kwargs) -> dict:
    """Read recent application logs, optionally filtered by level."""
    level = (level or "").strip().upper()
    lines = max(1, min(int(lines or 120), 500))
    log_file = Path(__file__).resolve().parents[3] / "logs" / "music_sub.log"
    if not log_file.exists():
        return {"lines": [], "total": 0, "level": level, "message": "日志文件不存在"}
    try:
        all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        raise ToolError(f"读取日志失败：{e}")
    if level:
        all_lines = [line for line in all_lines if f"[{level}]" in line or level in line]
    recent = all_lines[-lines:]
    return {"lines": recent, "total": len(all_lines), "level": level}


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "get_system_status": {"risk": "low", "function": get_system_status, "description": "获取 Music Sub 系统状态。", "parameters": {"type": "object", "properties": {}}},
    "get_library_stats": {"risk": "low", "function": get_library_stats, "description": "获取音乐库统计。", "parameters": {"type": "object", "properties": {}}},
    "search_library": {"risk": "low", "function": search_library, "description": "搜索本地音乐库。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "limit": {"type": "integer"}}}},
    "list_tasks": {"risk": "low", "function": list_tasks, "description": "列出最近下载任务。", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    "list_subscriptions": {"risk": "low", "function": list_subscriptions, "description": "列出订阅。", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    "search_pt": {"risk": "low", "function": search_pt, "description": "搜索 PT 音乐资源。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "sites": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}, "required": ["keyword"]}},
    "search_online": {"risk": "low", "function": search_online_tool, "description": "搜索在线音乐源。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}, "required": ["keyword"]}},
    "search_download_candidates": {"risk": "low", "function": search_download_candidates, "description": "同时搜索 PT 资源和在线音乐源，用于下载决策。用户说找资源、下载音乐、下载单曲/专辑时优先使用。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "sites": {"type": "array", "items": {"type": "string"}}, "sources": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}, "required": ["keyword"]}},
    "pause_task": {"risk": "medium", "function": pause_task, "description": "暂停下载任务。", "parameters": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    "resume_task": {"risk": "medium", "function": resume_task, "description": "继续下载任务。", "parameters": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    "create_subscription": {"risk": "medium", "function": create_subscription, "description": "创建一个 PT 音乐订阅。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "type": {"type": "string", "enum": ["artist", "album", "keyword"]}, "quality": {"type": "string"}, "sites": {"type": "string"}, "enabled": {"type": "boolean"}}, "required": ["keyword"]}},
    "download_torrent": {"risk": "high", "function": download_torrent, "description": "下载一个 PT 搜索结果并添加到 qBittorrent。必须使用 search_pt 返回的 site、torrent_id、title。", "parameters": {"type": "object", "properties": {"site": {"type": "string"}, "torrent_id": {"type": "string"}, "title": {"type": "string"}}, "required": ["site", "torrent_id"]}},
    "download_online_song": {"risk": "high", "function": download_online_song, "description": "下载一个在线音乐搜索结果并可选整理入库。必须使用 search_online 返回的完整 song 对象。", "parameters": {"type": "object", "properties": {"song": {"type": "object"}, "organize": {"type": "boolean"}}, "required": ["song"]}},
    "organize_task": {"risk": "medium", "function": organize_task, "description": "对已下载完成的任务执行整理和刮削入库。", "parameters": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    "rescrape_album": {"risk": "medium", "function": rescrape_album, "description": "重新刮削指定专辑的元数据。", "parameters": {"type": "object", "properties": {"artist": {"type": "string"}, "album": {"type": "string"}}, "required": ["artist", "album"]}},
    "complete_album": {"risk": "high", "function": complete_album, "description": "补齐本地专辑缺失曲目。dry_run=true 只预览候选；dry_run=false 会下载在线音源并整理入库，优先无损候选。", "parameters": {"type": "object", "properties": {"artist": {"type": "string"}, "album": {"type": "string"}, "dry_run": {"type": "boolean"}, "limit": {"type": "integer"}, "sources": {"type": "array", "items": {"type": "string"}}}, "required": ["artist", "album"]}},
    "query_library_health": {"risk": "low", "function": query_library_health, "description": "查询音乐库治理问题，例如缺封面、缺歌词、未刮削、CUE 候选、专辑艺人冲突。", "parameters": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["", "missing_cover", "missing_lyrics", "missing_duration", "unknown_artist", "unscraped", "cue_candidates", "album_artist_conflicts"]}, "limit": {"type": "integer"}}}},
    "read_recent_logs": {"risk": "low", "function": read_recent_logs, "description": "读取最近应用日志，用于诊断下载、刮削、助手、站点连接等错误。", "parameters": {"type": "object", "properties": {"lines": {"type": "integer"}, "level": {"type": "string", "enum": ["", "INFO", "WARNING", "ERROR", "DEBUG"]}}}},
}


def openai_tools(enabled_names: set[str] | list[str] | None = None) -> list[dict[str, Any]]:
    enabled = set(enabled_names or [])
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for name, spec in TOOL_SPECS.items()
    ]
    return [tool for tool in tools if not enabled or tool["function"]["name"] in enabled]


def execute_tool(db: Session, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = TOOL_SPECS.get(name)
    if not spec:
        raise ToolError(f"未知工具：{name}")
    fn: Callable[..., dict[str, Any]] = spec["function"]
    return fn(db=db, **(args or {}))


def tool_risk(name: str) -> str:
    return (TOOL_SPECS.get(name) or {}).get("risk", "high")


def tool_catalog(enabled_names: set[str] | list[str] | None = None) -> list[dict[str, Any]]:
    enabled = set(enabled_names or [])
    group_map = {
        "get_system_status": "系统",
        "get_library_stats": "音乐库",
        "search_library": "音乐库",
        "list_tasks": "任务",
        "list_subscriptions": "订阅",
        "search_pt": "搜索",
        "search_online": "搜索",
        "search_download_candidates": "搜索",
        "pause_task": "任务动作",
        "resume_task": "任务动作",
        "create_subscription": "订阅动作",
        "download_torrent": "下载动作",
        "download_online_song": "下载动作",
        "organize_task": "音乐库动作",
        "rescrape_album": "音乐库动作",
        "complete_album": "音乐库动作",
        "query_library_health": "音乐库",
        "read_recent_logs": "诊断",
    }
    return [
        {
            "name": name,
            "description": spec.get("description", ""),
            "risk": spec.get("risk", "high"),
            "group": group_map.get(name, "其他"),
            "requires_confirm_by_default": spec.get("risk") in {"medium", "high"},
            "enabled": (not enabled or name in enabled),
        }
        for name, spec in TOOL_SPECS.items()
    ]
