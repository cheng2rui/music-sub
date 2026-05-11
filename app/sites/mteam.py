"""M-Team (馒头) PT site adapter using API."""
import logging
from typing import Optional
from urllib.parse import urlparse
from app.sites.base import BaseSite, TorrentInfo

logger = logging.getLogger(__name__)

MUSIC_CATEGORIES = ["406", "408", "409"]


class MTeamSite(BaseSite):
    """M-Team adapter using their API."""

    name = "mteam"

    def __init__(self, url: str, api_key: str = "", token: str = "", **kwargs):
        super().__init__(url, **kwargs)
        self.api_key = api_key
        self.token = token
        domain = urlparse(self.url).netloc
        self._api_base = f"https://api.{domain}"

    def _get_headers(self) -> dict:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def search(self, keyword: str) -> list[TorrentInfo]:
        """Search M-Team for music torrents."""
        url = f"{self._api_base}/api/torrent/search"
        payload = {
            "keyword": keyword,
            "categories": MUSIC_CATEGORIES,
            "pageNumber": 1,
            "pageSize": 50,
            "visible": 1,
        }
        try:
            resp = self._post(url, json=payload, headers=self._get_headers())
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"[mteam] Search failed: {e}")
            return []

        results = []
        for item in data.get("data", {}).get("data", []):
            torrent = item.get("torrent", {})
            status = item.get("status", {})
            results.append(TorrentInfo(
                site=self.name,
                torrent_id=str(torrent.get("id", "")),
                title=torrent.get("name", ""),
                size=float(torrent.get("size", 0)),
                seeders=int(status.get("seeders", 0)),
                leechers=int(status.get("leechers", 0)),
                upload_time=torrent.get("createdDate", ""),
                free=status.get("discount", "") == "FREE",
            ))
        return results

    def download_torrent(self, torrent_id: str) -> Optional[bytes]:
        """Get download token and fetch .torrent file."""
        url = f"{self._api_base}/api/torrent/genDlToken"
        payload = {"id": torrent_id}
        try:
            resp = self._post(url, json=payload, headers=self._get_headers())
            resp.raise_for_status()
            data = resp.json()
            dl_url = data.get("data", "")
            if not dl_url:
                return None
            torrent_resp = self._get(dl_url)
            torrent_resp.raise_for_status()
            return torrent_resp.content
        except Exception as e:
            logger.error(f"[mteam] Download torrent failed: {e}")
            return None
