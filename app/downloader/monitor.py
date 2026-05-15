"""Download completion monitor."""
import logging
from app.downloader.qbittorrent import qb_client

logger = logging.getLogger(__name__)

PROCESSED_TAG = "music-sub-done"


def get_newly_completed() -> list[dict]:
    """Get torrents that are completed but not yet processed."""
    completed = qb_client.get_completed()
    return [t for t in completed if PROCESSED_TAG not in (t.get("tags") or "")]


def mark_processed(torrent_hash: str):
    """Mark a torrent as processed.

    Online/direct downloads use synthetic hashes and are not present in qB.
    """
    if not torrent_hash or str(torrent_hash).startswith("online:") or str(torrent_hash).startswith("SIMULATED_"):
        return
    qb_client.add_tag(torrent_hash, PROCESSED_TAG)
