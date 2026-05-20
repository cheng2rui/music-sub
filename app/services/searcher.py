"""Multi-site search aggregator.

The heavy lifting now lives in :mod:`app.services.pt_search`. Legacy helpers in
this module are kept so subscriptions and the existing /api/search endpoint keep
working while the rest of the app migrates to the new chain.
"""
import logging
import uuid
from typing import Optional
import app.config as cfg_module
from app.sites.base import BaseSite, TorrentInfo
from app.sites.mteam import MTeamSite
from app.sites.opencd import OpenCDSite
from app.sites.ptclub import PTClubSite
from app.sites.dismusic import DisMusicSite
from app.services.pt_search import MusicSearchChain, SearchRequest, SearchResponse
from app.services.subscription import get_all_subscriptions, update_last_search
from app.services.online_music import download_online_song, search_online
from app.services.pipeline import _process_completed_torrent
from app.services.notify import notify_download_added
from app.downloader.qbittorrent import qb_client, torrent_info_hash
from app.models import DownloadTask
from app.db import SessionLocal

logger = logging.getLogger(__name__)

SITE_CLASSES = {
    "mteam": MTeamSite,
    "opencd": OpenCDSite,
    "ptclub": PTClubSite,
    "dismusic": DisMusicSite,
}

VIDEO_EXCLUDE_TERMS = [
    # 容器/编码/分辨率 — 出现这些词几乎肯定是视频
    "mp4", "mkv", "avi", "web-dl", "webrip", "bluray", "blu-ray",
    "bdrip", "dvdrip", "hdtv", "hdrip", "dvdiso", "dvd-iso", "bdiso", "bd-iso",
    "h.264", "h264", "h.265", "h265", "x264", "x265", "hevc", "avc",
    "2160p", "1080p", "720p", "480p", "576p", "4k uhd", "4kuhd", " 4k ", "uhd ", "60fps", "hdr",
    "remux", "3d-bd",
    # 字幕/修复类也几乎都是视频资源
    "中字", "字幕", "修复版", "修復版",
    # 明确是 MV / 视频类型
    "music video", " mv ", "[mv]", "：mv", "｜mv", "·mv",
]

AUDIO_HINT_TERMS = [
    "flac", "mp3", "ape", "wav", "m4a", "aac", "alac", "cue", "hi-res",
    "hires", "lossless", "无损", "無損", "320", "24bit", "16bit",
    "dsd", "dsf", "dff", "整轨", "分轨", "web flac", "web-flac",
]

TYPE_MAX_SIZE_BYTES = {
    "song": 500 * 1024 * 1024,
    "album": 8 * 1024 * 1024 * 1024,
    "keyword": 3 * 1024 * 1024 * 1024,
}

ONLINE_SOURCES = ["qq", "migu", "kugou", "netease", "kuwo"]


def _source_preference(sub) -> str:
    preference = (getattr(sub, "source_preference", None) or "pt").strip()
    return preference if preference in {"pt", "online_first", "online_only"} else "pt"


def _get_site_instance(name: str) -> Optional[BaseSite]:
    """Create a site instance from config."""
    site_cfg = cfg_module.config.sites.get(name)
    if not site_cfg or not site_cfg.enabled:
        return None
    if not site_cfg.url:
        return None
    cls = SITE_CLASSES.get(name)
    if not cls:
        return None
    kwargs = {"url": site_cfg.url}
    if site_cfg.api_key:
        kwargs["api_key"] = site_cfg.api_key
    if site_cfg.token:
        kwargs["token"] = site_cfg.token
    if site_cfg.cookie:
        kwargs["cookie"] = site_cfg.cookie
    return cls(**kwargs)


def search_sites(keyword: str, site_names: list[str] = None,
                 *, exclude_video: bool = True) -> list[TorrentInfo]:
    """Legacy entry point. Now backed by :class:`MusicSearchChain`.

    The chain already filters out video-like releases via the ranker.
    ``exclude_video=False`` keeps the previous "raw merge" behaviour for callers
    that explicitly want unfiltered output, falling back to a simple parallel
    site fan-out without music-aware penalties.
    """
    if exclude_video:
        response = search_with_chain(keyword, sites=site_names)
        return response.to_legacy()

    results: list[TorrentInfo] = []
    sites_to_search = site_names or list(cfg_module.config.sites.keys())
    for name in sites_to_search:
        site = _get_site_instance(name)
        if not site:
            continue
        try:
            results.extend(site.search(keyword) or [])
        except Exception as e:
            logger.error(f"[{name}] Search error: {e}")
    results.sort(key=lambda t: t.seeders, reverse=True)
    return results


def search_with_chain(keyword: str, sites: list[str] | None = None,
                      *, type: str = "keyword", artist: str = "", album: str = "",
                      title: str = "", quality: str = "any", limit: int = 60,
                      timeout: float = 15.0) -> SearchResponse:
    """Run the new MusicSearchChain and return the structured response."""
    request = SearchRequest(
        keyword=keyword,
        sites=sites or [],
        type=type,
        artist=artist,
        album=album,
        title=title,
        quality=quality,
        limit=limit,
        timeout=timeout,
    )
    return MusicSearchChain().search(request)



def _split_keywords(keyword: str) -> list[str]:
    """Split a subscription keyword into non-empty lower-case terms."""
    return [part.strip().lower() for part in keyword.replace("　", " ").split() if part.strip()]


def _normalize_match_text(value: str) -> str:
    return " ".join(_split_keywords(value or ""))


def _song_downloaded_for_subscription(sub, db) -> bool:
    if sub.type != "song":
        return False
    keyword = _normalize_match_text(sub.keyword)
    if not keyword:
        return False
    for task in db.query(DownloadTask).filter(DownloadTask.torrent_hash.like("online:%")).all():
        if keyword == _normalize_match_text(task.torrent_name or ""):
            return True
    return False


def _looks_like_video(title: str) -> bool:
    """Return True when a torrent title is very likely video instead of an audio release.

    仅依赖“容器/编码/分辨率/MV”这种硬信号，不再把“演唱会”这种体裁
    字眼当作死判（蔡依林 《唯舞独尊演唱会纪实》 依然是面向音频的专辑）。
    """
    lower = " " + title.lower() + " "  # 加边界便于“ mv ”之类的词边界检测
    return any(term in lower for term in VIDEO_EXCLUDE_TERMS)


def _has_audio_hint(title: str) -> bool:
    """Return True when a torrent title contains common music/audio release hints."""
    lower = title.lower()
    return any(term in lower for term in AUDIO_HINT_TERMS)


def _filter_subscription_results(results: list[TorrentInfo], sub) -> list[TorrentInfo]:
    """Apply subscription matching, quality, media-type, and size filters.

    Auto-download should be conservative: it is better to skip a dubious video result than
    to burn PT download limits or fill qB with stalled 4K concert/MV torrents.
    """
    keyword_lower = sub.keyword.lower().strip()
    words = _split_keywords(sub.keyword)

    if sub.type == "artist":
        results = [r for r in results if keyword_lower in r.title.lower()]
    elif sub.type == "song":
        # Song subscriptions created from playlists are usually "title artist".
        # Require every token to appear and keep results small/audio-like.
        results = [r for r in results if words and all(w in r.title.lower() for w in words)]
    elif sub.type == "album":
        results = [r for r in results if keyword_lower in r.title.lower()]
    elif sub.type == "keyword":
        # Keep keyword subscriptions conservative too; PT search may return loosely related items.
        results = [r for r in results if keyword_lower in r.title.lower()]

    if sub.quality == "flac":
        results = [r for r in results if "flac" in r.title.lower()]
    elif sub.quality == "mp3":
        results = [r for r in results if "mp3" in r.title.lower() or "320" in r.title.lower()]

    max_size = TYPE_MAX_SIZE_BYTES.get(sub.type)
    if max_size:
        results = [r for r in results if not r.size or r.size <= max_size]

    # Keyword/artist subscriptions are broad; keep only audio-looking results and drop video hints.
    # For explicit quality filters, the quality term itself is a strong audio hint.
    filtered = []
    for result in results:
        if _looks_like_video(result.title):
            logger.info(f"Skip likely video result: {result.title}")
            continue
        if sub.quality == "any" and sub.type in {"artist", "keyword"} and not _has_audio_hint(result.title):
            logger.info(f"Skip result without audio hint: {result.title}")
            continue
        filtered.append(result)
    return filtered


def fetch_torrent_info_hash(site_name: str, torrent_id: str) -> tuple[Optional[str], Optional[bytes]]:
    """Download a torrent file and return (info_hash, content) without adding it to qB."""
    site = _get_site_instance(site_name)
    if not site:
        logger.error(f"Site {site_name} not available")
        return None, None

    torrent_content = site.download_torrent(torrent_id)
    if not torrent_content:
        logger.error(f"Failed to download torrent {torrent_id} from {site_name}")
        return None, None

    info_hash = torrent_info_hash(torrent_content)
    if not info_hash:
        logger.error(f"Invalid torrent payload from {site_name}:{torrent_id}")
        return None, None
    return info_hash.lower(), torrent_content


def download_torrent_content(torrent_content: bytes) -> Optional[str]:
    """Add already-fetched torrent content to qB and return its info hash."""
    torrent_hash = qb_client.add_torrent(torrent_content)
    if torrent_hash:
        logger.info(f"Added torrent to QB: {torrent_hash}")
    return torrent_hash


def download_from_site(site_name: str, torrent_id: str) -> Optional[str]:
    """Download a torrent from a site and add to QB.

    Returns torrent hash or None.
    """
    _, torrent_content = fetch_torrent_info_hash(site_name, torrent_id)
    if not torrent_content:
        return None
    return download_torrent_content(torrent_content)


def _best_online_candidate(keyword: str, limit: int = 8) -> dict | None:
    """Return the best downloadable online candidate for a subscription keyword."""
    rows = search_online(keyword, sources=ONLINE_SOURCES, limit=limit)
    for row in rows:
        if row.get("disabled"):
            continue
        if row.get("url") or row.get("song_id"):
            return row
    return None


def _download_online_for_subscription(sub, db) -> bool:
    """Download and organize one online match for an online-priority subscription."""
    candidate = _best_online_candidate(sub.keyword)
    if not candidate:
        logger.info(f"No downloadable online candidate for subscription: {sub.keyword}")
        return False

    title = candidate.get("title") or candidate.get("filename") or sub.keyword
    artist = candidate.get("artist") or ""
    task_name = f"{title} - {artist}".strip(" -")
    source = candidate.get("source") or "online"
    normalized_task_name = _normalize_match_text(task_name)

    existing_task = db.query(DownloadTask).filter(
        DownloadTask.torrent_hash.like("online:%")
    ).filter(DownloadTask.torrent_name.ilike(f"%{title}%")).first()
    if existing_task and _normalize_match_text(existing_task.torrent_name or "") == normalized_task_name:
        logger.info(f"Online subscription result already tracked: {task_name}")
        return True

    file_path = download_online_song(candidate)
    synthetic_hash = f"online:{uuid.uuid4().hex}"
    task = DownloadTask(
        subscription_id=sub.id,
        torrent_name=task_name,
        torrent_hash=synthetic_hash,
        site=source,
        size=float(candidate.get("size") or 0),
        status="downloaded",
        save_path=file_path,
    )
    db.add(task)
    db.commit()

    _process_completed_torrent({
        "hash": synthetic_hash,
        "name": task_name,
        "content_path": file_path,
        "metadata": {
            "source": source,
            "song_id": candidate.get("song_id") or "",
            "title": candidate.get("title") or title,
            "artist": artist,
            "album": candidate.get("album") or "",
            "duration": candidate.get("duration") or 0,
        },
    })
    logger.info(f"Auto-downloaded online subscription: {task_name} ({source})")
    notify_download_added(task_name, source)
    return True


def search_all_subscriptions():
    """Search all enabled subscriptions and auto-download new matches."""
    subscriptions = get_all_subscriptions(enabled_only=True)
    if not subscriptions:
        return

    db = SessionLocal()
    try:
        for sub in subscriptions:
            logger.info(f"Searching subscription [{sub.type}]: {sub.keyword}")
            preference = _source_preference(sub)
            if _song_downloaded_for_subscription(sub, db):
                logger.info(f"Song subscription already downloaded online, skip: {sub.keyword}")
                update_last_search(sub.id)
                continue
            if preference in {"online_first", "online_only"}:
                try:
                    if _download_online_for_subscription(sub, db):
                        update_last_search(sub.id)
                        continue
                except Exception as e:
                    logger.warning(f"Online subscription download failed for {sub.keyword}: {e}")
                    if preference == "online_only":
                        update_last_search(sub.id)
                        continue

            sites = sub.sites.split(",") if sub.sites != "all" else None
            results = search_sites(sub.keyword, sites)

            before_count = len(results)
            results = _filter_subscription_results(results, sub)
            logger.info(
                f"Subscription filter kept {len(results)}/{before_count} results for "
                f"[{sub.type}/{sub.quality}] {sub.keyword}"
            )

            # Check for results already downloaded/attempted globally. Subscription titles can
            # overlap, and PT sites may rate-limit repeated .torrent downloads even if qB already
            # has the task. Keep this global instead of per-subscription to avoid hammering sites.
            existing_names = {
                t.torrent_name
                for t in db.query(DownloadTask).all()
            }
            existing_active_hashes = {
                t.hash.lower()
                for t in qb_client.client.torrents_info(category=cfg_module.config.qbittorrent.category)
                if getattr(t, "hash", None)
            }

            for torrent in results[:3]:  # Limit auto-downloads
                if torrent.title in existing_names:
                    continue

                # Auto-download
                torrent_hash = download_from_site(torrent.site, torrent.torrent_id)
                if torrent_hash:
                    normalized_hash = torrent_hash.lower()
                    existing_task = db.query(DownloadTask).filter(
                        DownloadTask.torrent_hash == normalized_hash
                    ).first()
                    if existing_task:
                        existing_names.add(torrent.title)
                        logger.info(f"Already tracked by hash, skip task insert: {torrent.title} ({normalized_hash})")
                        continue

                    if normalized_hash in existing_active_hashes:
                        logger.info(f"Already present in qBittorrent, skip duplicate task: {torrent.title} ({normalized_hash})")
                        continue

                    task = DownloadTask(
                        subscription_id=sub.id,
                        torrent_name=torrent.title,
                        torrent_hash=normalized_hash,
                        site=torrent.site,
                        size=torrent.size,
                        status="downloading",
                    )
                    db.add(task)
                    db.commit()
                    existing_names.add(torrent.title)
                    existing_active_hashes.add(normalized_hash)
                    logger.info(f"Auto-downloaded: {torrent.title}")
                    notify_download_added(torrent.title, torrent.site)

            update_last_search(sub.id)
    finally:
        db.close()
