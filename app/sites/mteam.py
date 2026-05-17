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
        """Search M-Team for music torrents.

        馈头 keyword 是字面 substring 匹配，多词中间加连字符/多个空格会令命中为 0。
        策略：
          1. 原样 keyword 走一次
          2. 如果 0 结果，归一化（多余空白/连字符合并、去掉中间“-”）再走一次
          3. 如果仍为 0 且是多词，按最长词单独走一次，最后在本地过滤“所有词都出现”
        """
        results = self._search_one(keyword)
        if results:
            return results

        normalized = self._normalize_keyword(keyword)
        if normalized and normalized != keyword:
            results = self._search_one(normalized)
            if results:
                return results

        words = [w for w in self._split_words(keyword) if len(w) > 1]
        if len(words) > 1:
            # 按词长倒序依次尝试单词搜索，本地过滤“所有词都出现”
            lowered_words = [w.lower() for w in words]
            for word in sorted(words, key=len, reverse=True):
                broad = self._search_one(word)
                if not broad:
                    continue
                hits = [r for r in broad if all(w in r.title.lower() for w in lowered_words)]
                if hits:
                    return hits
        return []

    @staticmethod
    def _normalize_keyword(keyword: str) -> str:
        import re
        # 合并多余空白，以及各种带连字符的分隔（包括中间“-”、全角“－”、点、斜杠等）
        # 这里包括“蔡依林-什么什么”这种两侧没空格的连字符。
        cleaned = re.sub(r"[\-\u2010-\u2015\uff0d\u30fb\\\/\|\u3001\u3002,\.;]+", " ", keyword)
        cleaned = re.sub(r"[\s\u3000]+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _split_words(keyword: str) -> list[str]:
        normalized = MTeamSite._normalize_keyword(keyword)
        return [w for w in normalized.split() if w]

    def _search_one(self, keyword: str) -> list[TorrentInfo]:
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
            logger.error(f"[mteam] Search failed for {keyword!r}: {e}")
            return []

        results = []
        for item in data.get("data", {}).get("data", []):
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
