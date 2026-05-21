"""Unified download candidate helpers for PT and online music results."""
from __future__ import annotations

from typing import Any


def _size_gb(value: float | int | None) -> float:
    return round(float(value or 0) / 1024 / 1024 / 1024, 2)


def build_pt_candidate(item, *, rank: int | None = None) -> dict[str, Any]:
    """Normalize a scored PT search item into a common candidate shape."""
    torrent = item.torrent
    title = torrent.title or ""
    return {
        "id": f"pt:{torrent.site}:{torrent.torrent_id}",
        "source_type": "pt",
        "source": torrent.site,
        "rank": rank,
        "title": title,
        "artist": "",
        "album": "",
        "quality": item.quality or "",
        "format": item.media_format or "",
        "size": torrent.size or 0,
        "size_gb": _size_gb(torrent.size),
        "seeders": torrent.seeders,
        "leechers": torrent.leechers,
        "free": bool(torrent.free),
        "score": item.score,
        "downloadable": True,
        "disabled": False,
        "reasons": item.reasons or [],
        "download_tool": "download_torrent",
        "download_args": {
            "site": torrent.site,
            "torrent_id": torrent.torrent_id,
            "title": title,
        },
        "raw": {
            "site": torrent.site,
            "torrent_id": torrent.torrent_id,
            "title": title,
            "size": torrent.size,
            "seeders": torrent.seeders,
            "leechers": torrent.leechers,
            "free": torrent.free,
        },
    }


def build_online_candidate(item: dict[str, Any], *, rank: int | None = None) -> dict[str, Any]:
    """Normalize an online music result into a common candidate shape."""
    title = item.get("title") or item.get("filename") or ""
    source = item.get("source") or "online"
    disabled = bool(item.get("disabled"))
    downloadable = not disabled and bool(item.get("url") or item.get("song_id"))
    song = dict(item)
    song["download_args"] = {"song": song, "organize": True}
    return {
        "id": f"online:{source}:{item.get('song_id') or title}",
        "source_type": "online",
        "source": source,
        "rank": rank,
        "title": title,
        "artist": item.get("artist") or "",
        "album": item.get("album") or "",
        "quality": item.get("quality") or "",
        "format": item.get("format") or "mp3",
        "duration": item.get("duration") or 0,
        "bitrate": item.get("bitrate") or 0,
        "size": item.get("size") or 0,
        "size_gb": _size_gb(item.get("size") or 0),
        "score": item.get("score"),
        "downloadable": downloadable,
        "disabled": disabled,
        "reasons": ["online_direct"] if downloadable else ["online_unavailable"],
        "download_tool": "download_online_song",
        "download_args": {"song": item, "organize": True},
        "raw": song,
    }


def legacy_pt_item(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return the old assistant PT item shape for compatibility."""
    raw = candidate.get("raw") or {}
    return {
        "site": raw.get("site") or candidate.get("source"),
        "torrent_id": raw.get("torrent_id"),
        "title": candidate.get("title"),
        "size_gb": candidate.get("size_gb"),
        "seeders": candidate.get("seeders", 0),
        "leechers": candidate.get("leechers", 0),
        "free": candidate.get("free", False),
        "score": candidate.get("score"),
        "quality": candidate.get("quality"),
        "format": candidate.get("format"),
        "reasons": candidate.get("reasons") or [],
        "download_args": candidate.get("download_args") or {},
        "candidate_id": candidate.get("id"),
    }


def legacy_online_item(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return the old assistant online item shape for compatibility."""
    raw = dict(candidate.get("raw") or {})
    raw["download_args"] = candidate.get("download_args") or {}
    raw["candidate_id"] = candidate.get("id")
    return raw
