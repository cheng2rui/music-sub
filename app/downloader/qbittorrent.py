"""qBittorrent downloader integration."""
import hashlib
import logging
from typing import Optional
import qbittorrentapi
from app.config import config

logger = logging.getLogger(__name__)


def _decode_bencode(data: bytes, pos: int = 0):
    """Decode enough bencode to validate .torrent files and locate the info dict."""
    if pos >= len(data):
        raise ValueError("unexpected end of data")
    token = data[pos:pos + 1]
    if token == b"i":
        end = data.index(b"e", pos)
        return int(data[pos + 1:end]), end + 1
    if token == b"l":
        pos += 1
        items = []
        while data[pos:pos + 1] != b"e":
            item, pos = _decode_bencode(data, pos)
            items.append(item)
        return items, pos + 1
    if token == b"d":
        pos += 1
        items = {}
        while data[pos:pos + 1] != b"e":
            key, pos = _decode_bencode(data, pos)
            value_start = pos
            value, pos = _decode_bencode(data, pos)
            items[key] = (value, value_start, pos)
        return items, pos + 1
    if b"0" <= token <= b"9":
        colon = data.index(b":", pos)
        length = int(data[pos:colon])
        start = colon + 1
        end = start + length
        if end > len(data):
            raise ValueError("string extends past end of data")
        return data[start:end], end
    raise ValueError(f"invalid bencode token: {token!r}")


def torrent_info_hash(torrent_content: bytes) -> Optional[str]:
    """Return BitTorrent v1 info hash for a .torrent payload, or None if invalid."""
    try:
        decoded, end = _decode_bencode(torrent_content)
        if end != len(torrent_content) or not isinstance(decoded, dict):
            return None
        info_entry = decoded.get(b"info")
        if not info_entry:
            return None
        _, info_start, info_end = info_entry
        return hashlib.sha1(torrent_content[info_start:info_end]).hexdigest()
    except Exception:
        return None


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
        """Add torrent to qBittorrent. Returns the torrent's own info hash or None."""
        cfg = config.qbittorrent
        expected_hash = torrent_info_hash(torrent_content)
        if not expected_hash:
            preview = torrent_content[:200].decode("utf-8", errors="replace") if torrent_content else ""
            logger.error(f"Invalid torrent payload, refusing to add. Preview: {preview!r}")
            return None

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

            # Do not infer the hash from "latest torrent"; concurrent or duplicate adds can make
            # that point at a different task. The .torrent info hash is the canonical identifier.
            torrent = self.client.torrents_info(torrent_hashes=expected_hash)
            if torrent:
                return expected_hash

            logger.warning(f"Torrent add accepted but hash not visible in qBittorrent yet: {expected_hash}")
            return expected_hash
        except Exception as e:
            logger.error(f"Failed to add torrent {expected_hash}: {e}")
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

    def remove_tag(self, torrent_hash: str, tag: str):
        """Remove a tag from a torrent."""
        try:
            self.client.torrents_remove_tags(tags=tag, torrent_hashes=torrent_hash)
        except Exception as e:
            logger.error(f"Failed to remove tag: {e}")

    def pause_torrent(self, torrent_hash: str) -> bool:
        """Pause/stop a torrent by hash."""
        try:
            self.client.torrents_pause(torrent_hashes=torrent_hash)
            return True
        except Exception as e:
            logger.error(f"Failed to pause torrent {torrent_hash}: {e}")
            return False

    def resume_torrent(self, torrent_hash: str) -> bool:
        """Resume/start a torrent by hash."""
        try:
            self.client.torrents_resume(torrent_hashes=torrent_hash)
            return True
        except Exception as e:
            logger.error(f"Failed to resume torrent {torrent_hash}: {e}")
            return False

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> bool:
        """Delete a torrent from qBittorrent. Does not delete files by default."""
        try:
            # Clear internal processed marker first so a future re-import can be processed again.
            self.remove_tag(torrent_hash, "music-sub-done")
            self.client.torrents_delete(delete_files=delete_files, torrent_hashes=torrent_hash)
            return True
        except Exception as e:
            logger.error(f"Failed to delete torrent {torrent_hash}: {e}")
            return False

    def get_torrents_by_hash(self, hashes: list[str]) -> dict[str, dict]:
        """Return qBittorrent state keyed by lowercase hash."""
        hashes = [h.lower() for h in hashes if h]
        if not hashes:
            return {}
        try:
            torrents = self.client.torrents_info(torrent_hashes="|".join(hashes))
        except Exception as e:
            logger.error(f"Failed to get torrent states: {e}")
            return {}

        result: dict[str, dict] = {}
        for t in torrents:
            tracker_msg = self._best_tracker_message(t.hash)
            result[t.hash.lower()] = {
                "qb_state": t.state,
                "progress": float(t.progress or 0),
                "download_speed": float(getattr(t, "dlspeed", 0) or 0),
                "upload_speed": float(getattr(t, "upspeed", 0) or 0),
                "eta": int(getattr(t, "eta", 0) or 0),
                "amount_left": float(getattr(t, "amount_left", 0) or 0),
                "size": float(getattr(t, "size", 0) or 0),
                "category": getattr(t, "category", "") or "",
                "tags": getattr(t, "tags", "") or "",
                "save_path": t.save_path,
                "content_path": t.content_path,
                "name": t.name,
                "tracker_msg": tracker_msg,
            }
        return result

    def _best_tracker_message(self, torrent_hash: str) -> str:
        """Return the most informative non-empty tracker message for diagnostics."""
        try:
            trks = self.client.torrents_trackers(torrent_hash=torrent_hash)
        except Exception:
            return ""
        # status: 0=disabled, 1=not contacted, 2=working, 3=updating, 4=not working
        # 优先拿“出错但有 msg”的那一条（如 Port 6881 is blacklisted）
        broken_msgs = []
        info_msgs = []
        for t in trks:
            url = t.get("url") or ""
            msg = (t.get("msg") or "").strip()
            status = t.get("status")
            if url.startswith("** ["):  # DHT/PeX/LSD pseudo trackers
                continue
            if status in (4,) and msg:
                broken_msgs.append(msg)
            elif msg:
                info_msgs.append(msg)
        return (broken_msgs or info_msgs or [""])[0][:200]

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
