"""Multi-site search aggregator."""
import logging
from typing import Optional
import app.config as cfg_module
from app.sites.base import BaseSite, TorrentInfo
from app.sites.mteam import MTeamSite
from app.sites.opencd import OpenCDSite
from app.sites.ptclub import PTClubSite
from app.sites.dismusic import DisMusicSite
from app.services.subscription import get_all_subscriptions, update_last_search
from app.services.notify import notify_download_added
from app.downloader.qbittorrent import qb_client
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
    "mv", "music video", "mp4", "mkv", "avi", "web-dl", "webrip", "bluray",
    "bdrip", "dvdrip", "h264", "h265", "x264", "x265", "hevc", "2160p",
    "1080p", "720p", "4k", "60fps", "ac3", "remux", "演唱会", "演唱會",
    "concert", "live concert", "dvd", "中字", "字幕", "修复", "修復", "repair",
]

AUDIO_HINT_TERMS = [
    "flac", "mp3", "ape", "wav", "m4a", "aac", "alac", "cue", "cd", "hi-res",
    "hires", "lossless", "无损", "無損", "320", "24bit", "16bit",
]

TYPE_MAX_SIZE_BYTES = {
    "song": 500 * 1024 * 1024,
    "album": 8 * 1024 * 1024 * 1024,
    "keyword": 3 * 1024 * 1024 * 1024,
}


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


def search_sites(keyword: str, site_names: list[str] = None) -> list[TorrentInfo]:
    """Search multiple PT sites for a keyword."""
    results = []
    sites_to_search = site_names or list(cfg_module.config.sites.keys())

    for name in sites_to_search:
        site = _get_site_instance(name)
        if not site:
            continue
        try:
            site_results = site.search(keyword)
            results.extend(site_results)
            logger.info(f"[{name}] Found {len(site_results)} results for '{keyword}'")
        except Exception as e:
            logger.error(f"[{name}] Search error: {e}")

    # Sort by seeders descending
    results.sort(key=lambda t: t.seeders, reverse=True)
    return results


def _split_keywords(keyword: str) -> list[str]:
    """Split a subscription keyword into non-empty lower-case terms."""
    return [part.strip().lower() for part in keyword.replace("　", " ").split() if part.strip()]


def _looks_like_video(title: str) -> bool:
    """Return True when a torrent title is very likely video instead of an audio release."""
    lower = title.lower()
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


def download_from_site(site_name: str, torrent_id: str) -> Optional[str]:
    """Download a torrent from a site and add to QB.

    Returns torrent hash or None.
    """
    site = _get_site_instance(site_name)
    if not site:
        logger.error(f"Site {site_name} not available")
        return None

    torrent_content = site.download_torrent(torrent_id)
    if not torrent_content:
        logger.error(f"Failed to download torrent {torrent_id} from {site_name}")
        return None

    torrent_hash = qb_client.add_torrent(torrent_content)
    if torrent_hash:
        logger.info(f"Added torrent to QB: {torrent_hash}")
    return torrent_hash


def search_all_subscriptions():
    """Search all enabled subscriptions and auto-download new matches."""
    subscriptions = get_all_subscriptions(enabled_only=True)
    if not subscriptions:
        return

    db = SessionLocal()
    try:
        for sub in subscriptions:
            logger.info(f"Searching subscription [{sub.type}]: {sub.keyword}")
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
