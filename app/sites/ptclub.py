"""PTClub (猫站) PT site adapter - NexusPHP style."""
import logging
import re
from typing import Optional

from app.sites.base import BaseSite, TorrentInfo

logger = logging.getLogger(__name__)


def _strip_tags(html: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", html or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_size(text: str) -> float:
    match = re.search(r"([\d.]+)\s*(KB|MB|GB|TB)", text or "", re.IGNORECASE)
    if not match:
        return 0.0
    value, unit = match.groups()
    multiplier = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[unit.upper()]
    try:
        return float(value) * multiplier
    except ValueError:
        return 0.0


def _parse_int(text: str) -> int:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else 0


class PTClubSite(BaseSite):
    """PTClub adapter.

    PTClub is NexusPHP based, but differs from OpenCD:
    - music category is ``cat406`` (not OpenCD's cat408)
    - listing links use ``details.php`` (not ``plugin_details.php``)
    """

    name = "ptclub"

    def __init__(self, url: str, cookie: str = "", **kwargs):
        super().__init__(url, **kwargs)
        if cookie:
            self._session.headers["Cookie"] = cookie

    def search(self, keyword: str) -> list[TorrentInfo]:
        params = {
            "search": keyword,
            "cat406": 1,
            "incldead": 0,
            "search_area": 0,
            "search_mode": 0,
        }
        try:
            resp = self._get(f"{self.url}/torrents.php", params=params)
            resp.raise_for_status()
            return self._parse_torrent_list(resp.text)
        except Exception as e:
            logger.error(f"[ptclub] Search failed: {e}")
            return []

    def _parse_torrent_list(self, html: str) -> list[TorrentInfo]:
        results: list[TorrentInfo] = []
        seen: set[str] = set()
        for row in re.findall(r"<tr[^>]*>[\s\S]*?</tr>", html or "", re.IGNORECASE):
            if "download.php?id=" not in row or "details.php?id=" not in row:
                continue
            dl = re.search(r"download\.php\?id=(\d+)", row)
            if not dl:
                continue
            torrent_id = dl.group(1)
            if torrent_id in seen:
                continue
            seen.add(torrent_id)

            title = ""
            title_match = re.search(
                r'<a\s+title="([^"]*)"\s+href="details\.php\?id=\d+[^>]*>[\s\S]*?</a>',
                row,
                re.IGNORECASE,
            )
            if title_match:
                title = title_match.group(1).strip()
            if not title:
                title_html = self._first_match(row, r'href="details\.php\?id=\d+[^>]*>[\s\S]*?<b>([\s\S]*?)</b>')
                title = _strip_tags(title_html)
            if not title:
                continue

            tail = row[row.find("</table>"):] if "</table>" in row else row
            cells = re.findall(r'<td class="rowfollow[^>]*>([\s\S]*?)</td>', tail, re.IGNORECASE)
            size = seeders = leechers = 0
            upload_time = ""
            if len(cells) >= 5:
                upload_time = _strip_tags(cells[1])
                size = _parse_size(_strip_tags(cells[2]))
                seeders = _parse_int(cells[3])
                leechers = _parse_int(cells[4])

            results.append(TorrentInfo(
                site=self.name,
                torrent_id=torrent_id,
                title=title,
                size=size,
                seeders=seeders,
                leechers=leechers,
                upload_time=upload_time,
                free=bool(re.search(r"pro_free|free|FREE|免费|免費", row)),
            ))
        return results

    @staticmethod
    def _first_match(text: str, pattern: str) -> str:
        match = re.search(pattern, text or "", re.IGNORECASE)
        return match.group(1) if match else ""

    def download_torrent(self, torrent_id: str) -> Optional[bytes]:
        try:
            resp = self._get(f"{self.url}/download.php?id={torrent_id}")
            resp.raise_for_status()
            if b"<!DOCTYPE" in resp.content[:100] or b"<html" in resp.content[:200].lower():
                logger.error("[ptclub] Got HTML instead of torrent - cookie expired?")
                return None
            return resp.content
        except Exception as e:
            logger.error(f"[ptclub] Download torrent failed: {e}")
            return None
