"""qBittorrent downloader integration."""
import logging
from typing import Optional
import qbittorrentapi
from app.config import config

logger = logging.getLogger(__name__)


class QBClient:
    """qBittorrent API client wrapper."""

    def __init__(self):
        self._client: Optional[qbittorrentapi.Client] = None

    def _connect(self) -> qbittorrentapi.Client:
        if self._client is None:
            cfg = config.qbittorrent
            self._client = qbittorrentapi.Client(
                host=cfg.host,
                username=cfg.username,
                password=cfg.password,
            )
            try:
                self._client.auth_log_in()
                logger.info(f"Connected to qBittorrent at {cfg.host}")
            except Exception as e:
                # qBittorrent can be configured with WebUI auth bypass for trusted subnets.
                # In that mode /api/v2/auth/login may fail, but other APIs still work.
                try:
                    _ = self._client.app.version
                    logger.info(f"Connected to qBittorrent at {cfg.host} (auth bypass)")
                except Exception:
                    logger.error(f"Failed to connect to qBittorrent: {e}")
                    self._client = None
                    raise
        return self._client

    @property
    def client(self) -> qbittorrentapi.Client:
        return self._connect()

    def add_torrent(self, torrent_content: bytes, save_path: Optional[str] = None,
                    category: Optional[str] = None, tags: Optional[list[str]] = None) -> Optional[str]:
        """Add torrent to qBittorrent. Returns torrent hash or None."""
        cfg = config.qbittorrent
        try:
            result = self.client.torrents_add(
                torrent_files=torrent_content,
                save_path=save_path or cfg.save_path,
                category=category or cfg.category,
                tags=",".join(tags) if tags else cfg.tag,
                is_paused=False,
            )
            # qBittorrent/qbittorrentapi return value is not stable across versions
            # (commonly "Ok.", sometimes None/empty), while the torrent may already be added.
            if result not in (None, "", "Ok", "Ok."):
                logger.warning(f"qBittorrent add_torrent returned: {result}")

            torrents = self.client.torrents_info(
                category=category or cfg.category,
                sort="added_on",
                reverse=True,
                limit=5,
            )
            if not torrents:
                torrents = self.client.torrents_info(sort="added_on", reverse=True, limit=5)
            if torrents:
                return torrents[0].hash
            return None
        except Exception as e:
            logger.error(f"Failed to add torrent: {e}")
            return None

    def get_completed(self, category: Optional[str] = None, tag: Optional[str] = None) -> list[dict]:
        """Get completed torrents filtered by category/tag."""
        cfg = config.qbittorrent
        try:
            torrents = self.client.torrents_info(
                status_filter="completed",
                category=category or cfg.category,
                tag=tag or cfg.tag,
            )
            return [
                {
                    "hash": t.hash,
                    "name": t.name,
                    "save_path": t.save_path,
                    "content_path": t.content_path,
                    "size": t.size,
                    "added_on": t.added_on,
                    "completion_on": t.completion_on,
                    "tags": t.tags,
                }
                for t in torrents
            ]
        except Exception as e:
            logger.error(f"Failed to get completed torrents: {e}")
            return []

    def add_tag(self, torrent_hash: str, tag: str):
        """Add a tag to a torrent."""
        try:
            self.client.torrents_add_tags(tags=tag, torrent_hashes=torrent_hash)
        except Exception as e:
            logger.error(f"Failed to add tag: {e}")

    def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        """Get files in a torrent."""
        try:
            files = self.client.torrents_files(torrent_hash=torrent_hash)
            return [{"name": f.name, "size": f.size, "progress": f.progress} for f in files]
        except Exception as e:
            logger.error(f"Failed to get torrent files: {e}")
            return []

    def test_connection(self) -> tuple[bool, str]:
        """Test connection to qBittorrent."""
        try:
            client = self._connect()
            info = client.transfer_info()
            return True, f"Connected. DL: {info.dl_info_speed}, UL: {info.up_info_speed}"
        except Exception as e:
            return False, str(e)


qb_client = QBClient()
