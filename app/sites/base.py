"""Base class for PT site adapters."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import requests
import logging

logger = logging.getLogger(__name__)


@dataclass
class TorrentInfo:
    """Unified torrent search result."""
    site: str
    torrent_id: str
    title: str
    size: float = 0
    seeders: int = 0
    leechers: int = 0
    upload_time: str = ""
    free: bool = False
    download_url: str = ""


class BaseSite(ABC):
    """Base class for all PT site adapters."""

    name: str = "base"

    def __init__(self, url: str, **kwargs):
        self.url = url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self._timeout = kwargs.get("timeout", 30)

    @abstractmethod
    def search(self, keyword: str) -> list[TorrentInfo]:
        """Search for music torrents by keyword."""
        ...

    @abstractmethod
    def download_torrent(self, torrent_id: str) -> Optional[bytes]:
        """Download .torrent file content by ID."""
        ...

    def _get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self._timeout)
        return self._session.get(url, **kwargs)

    def _post(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self._timeout)
        return self._session.post(url, **kwargs)
