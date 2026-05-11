"""Multi-site search aggregator."""
import logging
from typing import Optional
from app.config import config
from app.sites.base import BaseSite, TorrentInfo
from app.sites.mteam import MTeamSite
from app.sites.opencd import OpenCDSite
from app.sites.ptclub import PTClubSite
from app.sites.dismusic import DisMusicSite
from app.services.subscription import get_all_subscriptions, update_last_search
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


def _get_site_instance(name: str) -> Optional[BaseSite]:
    """Create a site instance from config."""
    site_cfg = config.sites.get(name)
    if not site_cfg or not site_cfg.enabled:
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
    sites_to_search = site_names or list(config.sites.keys())

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
            logger.info(f"Searching subscription: {sub.keyword}")
            sites = sub.sites.split(",") if sub.sites != "all" else None
            results = search_sites(sub.keyword, sites)

            # Check for new results not already downloaded
            existing_names = {
                t.torrent_name
                for t in db.query(DownloadTask).filter(
                    DownloadTask.subscription_id == sub.id
                ).all()
            }

            for torrent in results[:3]:  # Limit auto-downloads
                if torrent.title in existing_names:
                    continue

                # Auto-download
                torrent_hash = download_from_site(torrent.site, torrent.torrent_id)
                if torrent_hash:
                    task = DownloadTask(
                        subscription_id=sub.id,
                        torrent_name=torrent.title,
                        torrent_hash=torrent_hash,
                        site=torrent.site,
                        size=torrent.size,
                        status="downloading",
                    )
                    db.add(task)
                    db.commit()
                    logger.info(f"Auto-downloaded: {torrent.title}")

            update_last_search(sub.id)
    finally:
        db.close()
