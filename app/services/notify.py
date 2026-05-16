"""Telegram notification service."""
import logging
import requests
import app.config as cfg_module

logger = logging.getLogger(__name__)


def _send(text: str) -> bool:
    """Send a message via Telegram bot. Returns True on success."""
    tg = cfg_module.config.notify.telegram
    if not tg.enabled or not tg.bot_token or not tg.chat_id:
        return False
    url = f"https://api.telegram.org/bot{tg.bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": tg.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        logger.warning(f"Telegram send failed: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def notify_download_added(torrent_name: str, site: str):
    """Notify when a new download is added."""
    tg = cfg_module.config.notify.telegram
    if not tg.on_download_added:
        return
    _send(f"⬇️ <b>开始下载</b>\n{torrent_name}\n来源: {site}")


def notify_download_complete(torrent_name: str, file_count: int):
    """Notify when a download completes."""
    tg = cfg_module.config.notify.telegram
    if not tg.on_download_complete:
        return
    _send(f"✅ <b>下载完成</b>\n{torrent_name}\n文件数: {file_count}")


def notify_scrape_complete(torrent_name: str, scraped: int, total: int):
    """Notify when scraping completes for an album."""
    tg = cfg_module.config.notify.telegram
    if not tg.on_scrape_complete:
        return
    _send(f"🎵 <b>刮削完成</b>\n{torrent_name}\n成功: {scraped}/{total}")


def notify_error(context: str, error: str):
    """Notify on error."""
    tg = cfg_module.config.notify.telegram
    if not tg.on_error:
        return
    _send(f"❌ <b>错误</b>\n{context}\n{error[:200]}")


def notify_cleanup_candidates(candidate_count: int, qb_and_db_count: int, db_only_count: int, total_size: float, total_amount_left: float):
    """Notify when cleanup dry-run finds dirty task candidates."""
    tg = cfg_module.config.notify.telegram
    if not getattr(tg, "on_cleanup_candidates", True):
        return
    size_mb = total_size / 1024 / 1024 if total_size else 0
    left_mb = total_amount_left / 1024 / 1024 if total_amount_left else 0
    _send(
        "🧹 <b>Music Sub 清理扫描发现候选</b>\n"
        f"候选任务: {candidate_count}\n"
        f"qB+DB: {qb_and_db_count} · 仅DB: {db_only_count}\n"
        f"影响大小: {size_mb:.1f} MB · 剩余未下载: {left_mb:.1f} MB\n"
        "请到任务列表执行清理扫描确认。"
    )
