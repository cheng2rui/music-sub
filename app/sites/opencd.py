"""Open.CD (皇后) PT site adapter - NexusPHP style."""
import logging
import re
from typing import Optional

from app.sites.base import BaseSite, TorrentInfo

logger = logging.getLogger(__name__)


# Detail link regex: OpenCD uses ``plugin_details.php?id=NNN`` instead of the
# stock NexusPHP ``details.php?id=NNN``. The ``a title`` attribute in their
# template ships with two spaces before ``href``; we handle that defensively.
_DETAIL_LINK_RE = re.compile(
    r'<a\s+title="([^"]*)"\s+href="plugin_details\.php\?id=(\d+)',
    re.IGNORECASE,
)

# OpenCD's listing rows start with a category cell. Use that signature to
# carve out the actual row slab regardless of nested ``torrentname`` tables.
_ROW_ANCHOR_RE = re.compile(
    r"<td class=\"rowfollow nowrap\" style='padding: 0px;width:48px;height:48px;text-align:right;background:url\(plugin/style/",
)


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_size(text: str) -> float:
    if not text:
        return 0.0
    match = re.search(r"([\d.]+)\s*(KB|MB|GB|TB)", text, re.IGNORECASE)
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
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


class OpenCDSite(BaseSite):
    """Open.CD adapter using NexusPHP web scraping."""

    name = "opencd"

    def __init__(self, url: str, cookie: str = "", **kwargs):
        super().__init__(url, **kwargs)
        if cookie:
            self._session.headers["Cookie"] = cookie

    def search(self, keyword: str) -> list[TorrentInfo]:
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
        results: list[TorrentInfo] = []
        anchors = [m.start() for m in _ROW_ANCHOR_RE.finditer(html)]
        for idx, start in enumerate(anchors):
            end = anchors[idx + 1] if idx + 1 < len(anchors) else len(html)
            row_html = html[start:end]
            link = _DETAIL_LINK_RE.search(row_html)
            if not link:
                continue
            title = link.group(1).strip()
            torrent_id = link.group(2)
            size_text, seeders_text, leechers_text, free, upload_text = self._extract_metrics(row_html)
            results.append(TorrentInfo(
                site=self.name,
                torrent_id=torrent_id,
                title=title,
                size=_parse_size(size_text),
                seeders=_parse_int(seeders_text),
                leechers=_parse_int(leechers_text),
                upload_time=upload_text,
                free=free,
            ))
        return results

    @staticmethod
    def _extract_metrics(row_html: str) -> tuple[str, str, str, bool, str]:
        if not row_html:
            return "", "", "", False, ""
        # Drop the nested torrentname table so we can split the row's top-level cells.
        flattened = re.sub(
            r"<table class=\"torrentname\"[\s\S]*?</table>",
            "<td>title</td>",
            row_html,
            count=1,
        )
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", flattened)
        # Top-level columns when row is healthy:
        #   0 分类 / 1 封面 / 2 标题 / 3 LOG / 4 评论 / 5 时间 / 6 大小 / 7 种子 / 8 下载 / 9 完成 / 10 发布者
        size_text = seeders_text = leechers_text = upload_text = ""
        if len(cells) >= 9:
            upload_text = _strip_tags(cells[5])
            size_text = _strip_tags(cells[6])
            seeders_text = _strip_tags(cells[7])
            leechers_text = _strip_tags(cells[8])
        free = bool(re.search(r"free|FREE|免費|免费|pro_free", row_html))
        return size_text, seeders_text, leechers_text, free, upload_text

    def download_torrent(self, torrent_id: str) -> Optional[bytes]:
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
