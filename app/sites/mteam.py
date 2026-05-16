"""M-Team (馒头) PT site adapter using API."""
import logging
from typing import Optional
from urllib.parse import urlparse
from app.sites.base import BaseSite, TorrentInfo

logger = logging.getLogger(__name__)

# M-Team web route https://kp.m-team.cc/browse/music?keyword= maps to API mode="music".
# Do not hard-code category IDs here: M-Team adds/changes music subcategories (e.g. new
# categories like 434), and an old fixed category list makes valid music releases disappear.
MUSIC_BROWSE_MODE = "music"


class MTeamSite(BaseSite):
    """M-Team adapter using their API."""

    name = "mteam"

    def __init__(self, url: str, api_key: str = "", token: str = "", **kwargs):
        super().__init__(url, **kwargs)
        self.api_key = api_key
        self.token = token
        domain = urlparse(self.url).netloc
        # M-Team main site is usually kp.m-team.cc, API host is api.m-team.cc.
        # Do not blindly prepend api. to kp.m-team.cc (api.kp.m-team.cc is invalid/unstable).
        if domain.startswith("kp.m-team.cc"):
            self._api_base = "https://api.m-team.cc"
        elif domain.startswith("api."):
            self._api_base = f"https://{domain}"
        else:
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
            "mode": MUSIC_BROWSE_MODE,
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
            # New M-Team API returns torrent fields at top-level; older wrappers may use {torrent, status}.
            torrent = item.get("torrent") or item
            status = item.get("status", {})
            results.append(TorrentInfo(
                site=self.name,
                torrent_id=str(torrent.get("id", "")),
                title=torrent.get("name", "") or torrent.get("smallDescr", ""),
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
            # M-Team expects form/query params here, not JSON body.
            # JSON body returns {code:1, message:"參數錯誤"}.
            resp = self._post(url, data=payload, headers=self._get_headers())
            resp.raise_for_status()
            data = resp.json()
            if str(data.get("code")) not in ("0", "200"):
                logger.error(f"[mteam] Download token failed: {data.get('message', data)}")
                return None
            dl_url = data.get("data", "")
            if not dl_url:
                return None
            torrent_resp = self._get(dl_url)
            torrent_resp.raise_for_status()
            return torrent_resp.content
        except Exception as e:
            logger.error(f"[mteam] Download torrent failed: {e}")
            return None
