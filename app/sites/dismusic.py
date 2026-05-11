"""Dis.Music (海豚) PT site adapter."""
import re
import logging
import urllib.parse
from typing import Optional
from app.sites.base import BaseSite, TorrentInfo

logger = logging.getLogger(__name__)

MUSIC_CATEGORIES = [408]


class DisMusicSite(BaseSite):
    """海豚 adapter."""

    name = "dismusic"

    def __init__(self, url: str, cookie: str = "", **kwargs):
        super().__init__(url, **kwargs)
        if cookie:
            self._session.headers["Cookie"] = cookie

    def search(self, keyword: str) -> list[TorrentInfo]:
        """Search HaiDan for music torrents."""
        params = {
            "search": keyword,
            "search_area": 0,
            "search_mode": 0,
            "incldead": 0,
            "cat": ",".join(str(c) for c in MUSIC_CATEGORIES),
        }
        try:
            resp = self._get(f"{self.url}/torrents.php", params=params)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "application/json" in ct:
                return self._parse_json(resp.json())
            return self._parse_html(resp.text)
        except Exception as e:
            logger.error(f"[dismusic] Search failed: {e}")
            return []

    def _parse_json(self, data: dict) -> list[TorrentInfo]:
        results = []
        for item in data.get("data", {}).get("torrents", []):
            results.append(TorrentInfo(
                site=self.name,
                torrent_id=str(item.get("torrent_id", "")),
                title=item.get("torrent_name", ""),
                size=float(item.get("size", 0)),
                seeders=int(item.get("seeders", 0)),
                leechers=int(item.get("leechers", 0)),
                upload_time=item.get("upload_time", ""),
                free=item.get("sp_state", 1) in [2, 4],
            ))
        return results

    def _parse_html(self, html: str) -> list[TorrentInfo]:
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
            ))
        return results

    def download_torrent(self, torrent_id: str) -> Optional[bytes]:
        """Download .torrent file."""
        try:
            resp = self._get(f"{self.url}/download.php?id={torrent_id}")
            resp.raise_for_status()
            if b"<!DOCTYPE" in resp.content[:100]:
                return None
            return resp.content
        except Exception as e:
            logger.error(f"[dismusic] Download torrent failed: {e}")
            return None
