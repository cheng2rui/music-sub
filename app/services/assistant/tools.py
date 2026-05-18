"""Assistant tool registry and implementations."""
from __future__ import annotations

import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import config
from app.models import DownloadTask, MusicFile, Subscription
from app.services.searcher import search_with_chain
from app.services.online_music import search_online
from app.downloader.qbittorrent import qb_client


class ToolError(RuntimeError):
    pass


def _size_gb(value: float | int | None) -> float:
    return round(float(value or 0) / 1024 / 1024 / 1024, 2)


def get_system_status(db: Session, **kwargs) -> dict:
    return {
        "version": "0.7.0",
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
            }
            for item in resp.results[:max(1, min(int(limit or 10), 30))]
        ],
    }


def search_online_tool(db: Session, keyword: str, sources: list[str] | None = None, limit: int = 10, **kwargs) -> dict:
    if not keyword:
        raise ToolError("缺少 keyword")
    return {"items": search_online(keyword, sources=sources, limit=max(1, min(int(limit or 10), 20)))}


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


TOOL_SPECS: dict[str, dict[str, Any]] = {
    "get_system_status": {"risk": "low", "function": get_system_status, "description": "获取 Music Sub 系统状态。", "parameters": {"type": "object", "properties": {}}},
    "get_library_stats": {"risk": "low", "function": get_library_stats, "description": "获取音乐库统计。", "parameters": {"type": "object", "properties": {}}},
    "search_library": {"risk": "low", "function": search_library, "description": "搜索本地音乐库。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "limit": {"type": "integer"}}}},
    "list_tasks": {"risk": "low", "function": list_tasks, "description": "列出最近下载任务。", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    "list_subscriptions": {"risk": "low", "function": list_subscriptions, "description": "列出订阅。", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    "search_pt": {"risk": "low", "function": search_pt, "description": "搜索 PT 音乐资源。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "sites": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}, "required": ["keyword"]}},
    "search_online": {"risk": "low", "function": search_online_tool, "description": "搜索在线音乐源。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}}, "required": ["keyword"]}},
    "pause_task": {"risk": "medium", "function": pause_task, "description": "暂停下载任务。", "parameters": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    "resume_task": {"risk": "medium", "function": resume_task, "description": "继续下载任务。", "parameters": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
}


def openai_tools() -> list[dict[str, Any]]:
    return [
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


def execute_tool(db: Session, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = TOOL_SPECS.get(name)
    if not spec:
        raise ToolError(f"未知工具：{name}")
    fn: Callable[..., dict[str, Any]] = spec["function"]
    return fn(db=db, **(args or {}))


def tool_risk(name: str) -> str:
    return (TOOL_SPECS.get(name) or {}).get("risk", "high")
