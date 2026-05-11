"""Open.CD (皇后) PT site adapter - NexusPHP style."""
import re
import logging
from typing import Optional
from app.sites.base import BaseSite, TorrentInfo

logger = logging.getLogger(__name__)


class OpenCDSite(BaseSite):
    """Open.CD adapter using NexusPHP web scraping."""

    name = "opencd"

    def __init__(self, url: str, cookie: str = "", **kwargs):
        super().__init__(url, **kwargs)
        if cookie:
            self._session.headers["Cookie"] = cookie

    def search(self, keyword: str) -> list[TorrentInfo]:
        """Search for music torrents."""
        params = {
            "search": keyword,
            "cat408": 1,
            "incldead": 0,
            "search_area": 0,
            "search_mode": 0,
        }
        try:
            resp = self._get(f"{self.url}/torrents.php", params=params)
            resp.raise_for_status()
            return self._parse_torrent_list(resp.text)
        except Exception as e:
            logger.error(f"[{self.name}] Search failed: {e}")
            return []

    def _parse_torrent_list(self, html: str) -> list[TorrentInfo]:
        """Parse NexusPHP torrent list HTML."""
        results = []
        rows = re.findall(
            r'<a[^>]*href="details\.php\?id=(\d+)[^"]*"[^>]*title="([^"]*)"',
            html
        )
        for tid, title in rows:
            results.append(TorrentInfo(
                site=self.name,
                torrent_id=tid,
                title=title.strip(),
                size=0,
                seeders=0,
            ))
        return results

    def download_torrent(self, torrent_id: str) -> Optional[bytes]:
        """Download .torrent file."""
        try:
            resp = self._get(f"{self.url}/download.php?id={torrent_id}")
            resp.raise_for_status()
            if b"<!DOCTYPE" in resp.content[:100]:
                logger.error(f"[{self.name}] Got HTML instead of torrent - cookie expired?")
                return None
            return resp.content
        except Exception as e:
            logger.error(f"[{self.name}] Download torrent failed: {e}")
            return None
