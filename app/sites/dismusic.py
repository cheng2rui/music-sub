"""Dis.Music (海豚) PT site adapter."""
import re
import html as html_lib
import logging
import urllib.parse
from typing import Optional
from app.sites.base import BaseSite, TorrentInfo

logger = logging.getLogger(__name__)



class DisMusicSite(BaseSite):
    """海豚 adapter."""

    name = "dismusic"

    def __init__(self, url: str, cookie: str = "", **kwargs):
        super().__init__(url, **kwargs)
        if cookie:
            self._session.headers["Cookie"] = cookie

    def search(self, keyword: str) -> list[TorrentInfo]:
        """Search Dis.Music (Gazelle style) for music torrents.

        Dis.Music does not use NexusPHP's ``search=`` query parameter. Its
        torrent page search form uses ``searchstr`` + ``searchsubmit=1``.
        The previous adapter sent NexusPHP params, which returned the browse
        page instead of actual keyword results and then parsed zero rows.
        """
        params = {
            "searchstr": keyword,
            "searchsubmit": 1,
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
        results: list[TorrentInfo] = []
        current_group = ""
        seen: set[str] = set()

        # Gazelle groups albums first, then lists concrete torrent editions in
        # following ``group_torrent`` rows. Keep the latest group title so each
        # edition has a useful searchable title.
        for row_match in re.finditer(r"<tr[^>]*>[\s\S]*?</tr>", html or "", re.IGNORECASE):
            row = row_match.group(0)
            row_group = ""
            if "group_info" in row:
                row_group = self._parse_group_title(row)
                current_group = row_group or current_group
            if "action=download" not in row:
                continue

            id_match = re.search(r"action=download(?:&amp;|&)id=(\d+)", row)
            if not id_match:
                continue
            torrent_id = id_match.group(1)
            if torrent_id in seen:
                continue
            seen.add(torrent_id)

            edition = ""
            if not row_group:
                edition = self._strip_tags(self._first_match(
                    row,
                    r'<a[^>]+href="torrents\.php\?id=\d+(?:&amp;|&)torrentid=\d+"[^>]*>([\s\S]*?)</a>',
                ))
            title = row_group or current_group
            if edition:
                title = f"{title} [{edition}]" if title else edition
            if not title:
                title = f"Dis.Music torrent {torrent_id}"

            results.append(TorrentInfo(
                site=self.name,
                torrent_id=torrent_id,
                title=title.strip(),
                size=self._parse_size(self._first_match(row, r'<td class="td_size[^>]*>([\s\S]*?)</td>')),
                seeders=self._parse_int(self._first_match(row, r'<td class="td_seeders[^>]*>([\s\S]*?)</td>')),
                leechers=self._parse_int(self._first_match(row, r'<td class="td_leechers[^>]*>([\s\S]*?)</td>')),
                upload_time=self._strip_tags(self._first_match(row, r'<td class="td_time[^>]*>([\s\S]*?)</td>')),
                free="usetoken=1" in row or "Free" in row or "免费" in row,
            ))
        return results

    @staticmethod
    def _first_match(text: str, pattern: str) -> str:
        match = re.search(pattern, text or "", re.IGNORECASE)
        return match.group(1) if match else ""

    @staticmethod
    def _strip_tags(html: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html or "")
        text = re.sub(r"&nbsp;|&#160;", " ", text)
        text = html_lib.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @classmethod
    def _parse_group_title(cls, row: str) -> str:
        info = cls._first_match(row, r'<div class="group_info[^>]*>([\s\S]*?)</div>')
        title = cls._strip_tags(info)
        # Drop leading action links and bookmark/action tail if present.
        title = re.sub(r"^\[\s*DL\s*\|\s*FL\s*\|\s*RP\s*\]\s*", "", title).strip()
        title = re.sub(r"加入收藏.*$", "", title).strip()
        return title

    @classmethod
    def _parse_size(cls, html: str) -> float:
        text = cls._strip_tags(html)
        match = re.search(r"([\d.]+)\s*(KB|MB|GB|TB)", text, re.IGNORECASE)
        if not match:
            return 0.0
        value, unit = match.groups()
        multiplier = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[unit.upper()]
        try:
            return float(value) * multiplier
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_int(html: str) -> int:
        digits = re.sub(r"[^0-9]", "", html or "")
        return int(digits) if digits else 0

    def download_torrent(self, torrent_id: str) -> Optional[bytes]:
        """Download .torrent file."""
        try:
            resp = self._get(f"{self.url}/torrents.php", params={"action": "download", "id": torrent_id})
            resp.raise_for_status()
            if b"<!DOCTYPE" in resp.content[:100]:
                return None
            return resp.content
        except Exception as e:
            logger.error(f"[dismusic] Download torrent failed: {e}")
            return None
