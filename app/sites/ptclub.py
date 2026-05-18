"""PTClub (猫站) PT site adapter - NexusPHP style."""
import logging
import re
from typing import Optional

from app.sites.base import BaseSite, TorrentInfo

logger = logging.getLogger(__name__)


_DETAIL_LINK_RE = re.compile(
    r'<a\s+title="([^"]*)"\s+href="details\.php\?id=(\d+)',
    re.IGNORECASE,
)

# PTClub torrent rows contain a nested ``torrentname`` table, so a plain
# ``<tr>...</tr>`` regex stops at the nested title row before the seed/leech
# columns.  Anchor on the category cell and slice until the next category cell
# instead.
_ROW_ANCHOR_RE = re.compile(
    r'<td\s+class=["\']rowfollow\s+nowrap["\']\s+valign=["\']middle["\']\s+style=["\']padding:\s*0px["\']',
    re.IGNORECASE,
)


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
        anchors = [m.start() for m in _ROW_ANCHOR_RE.finditer(html or "")]
        for idx, start in enumerate(anchors):
            end = anchors[idx + 1] if idx + 1 < len(anchors) else len(html or "")
            row = (html or "")[start:end]
            if "download.php?id=" not in row or "details.php?id=" not in row:
                continue
            link = _DETAIL_LINK_RE.search(row)
            dl = re.search(r"download\.php\?id=(\d+)", row)
            if link:
                title = link.group(1).strip()
                torrent_id = link.group(2)
            elif dl:
                torrent_id = dl.group(1)
                title_html = self._first_match(row, r'href="details\.php\?id=\d+[^>]*>[\s\S]*?<b>([\s\S]*?)</b>')
                title = _strip_tags(title_html)
            else:
                continue
            if not title or torrent_id in seen:
                continue
            seen.add(torrent_id)

            size_text, seeders_text, leechers_text, upload_time = self._extract_metrics(row)

            results.append(TorrentInfo(
                site=self.name,
                torrent_id=torrent_id,
                title=title,
                size=_parse_size(size_text),
                seeders=_parse_int(seeders_text),
                leechers=_parse_int(leechers_text),
                upload_time=upload_time,
                free=bool(re.search(r"pro_free|free|FREE|免费|免費", row)),
            ))
        return results

    @staticmethod
    def _extract_metrics(row_html: str) -> tuple[str, str, str, str]:
        if not row_html:
            return "", "", "", ""
        # Remove the nested title table before splitting top-level row cells.
        flattened = re.sub(
            r"<table class=\"torrentname\"[\s\S]*?</table>",
            "<td>title</td>",
            row_html,
            count=1,
            flags=re.IGNORECASE,
        )
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", flattened, re.IGNORECASE)
        # Top-level PTClub columns:
        #   0 分类 / 1 标题块 / 2 评论 / 3 时间 / 4 大小 / 5 种子 / 6 下载 / 7 完成 / 8 发布者
        if len(cells) >= 7:
            return (
                _strip_tags(cells[4]),
                _strip_tags(cells[5]),
                _strip_tags(cells[6]),
                _strip_tags(cells[3]),
            )
        return "", "", "", ""

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
