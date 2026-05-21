"""Download completion monitor."""
import logging
from app.downloader.qbittorrent import qb_client

logger = logging.getLogger(__name__)

PROCESSED_TAG = "已整理"
LEGACY_PROCESSED_TAGS = {"music-sub-done", PROCESSED_TAG}


def _tag_list(tags: str | list | None) -> set[str]:
    if isinstance(tags, list):
        return {str(t).strip() for t in tags if str(t).strip()}
    return {t.strip() for t in (tags or "").split(",") if t.strip()}


def get_newly_completed() -> list[dict]:
    """Get completed qB torrents tagged for Music Sub but not yet processed.

    Users may manually add the configured `music-sub` tag in qBittorrent. The
    qB client searches completed torrents by tag across all categories, then this
    filter skips anything already marked as processed.  Keep the old
    `music-sub-done` tag as a legacy marker so existing tasks are not imported
    again after upgrading to the clearer `已整理` label.
    """
    completed = qb_client.get_completed()
    return [t for t in completed if not (_tag_list(t.get("tags")) & LEGACY_PROCESSED_TAGS)]


def mark_processed(torrent_hash: str):
    """Mark a torrent as processed.

    Online/direct downloads use synthetic hashes and are not present in qB.
    """
    if not torrent_hash or str(torrent_hash).startswith("online:") or str(torrent_hash).startswith("SIMULATED_"):
        return
    qb_client.add_tag(torrent_hash, PROCESSED_TAG)
