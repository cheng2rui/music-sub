"""Telegram notification channel adapter."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

import app.config as cfg_module

logger = logging.getLogger(__name__)


@dataclass
class TelegramSendResult:
    channel: str
    ok: bool
    message: str = ""
    response: Any = None


def send_chat_action(target: str | None = None, action: str = "typing") -> None:
    tg = cfg_module.config.notify.telegram
    chat_id = target or tg.chat_id
    if not tg.enabled or not tg.bot_token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{tg.bot_token}/sendChatAction",
            json={"chat_id": chat_id, "action": action},
            timeout=5,
        )
    except Exception:
        pass


def start_typing(target: str | None = None, *, interval: float = 4.5, max_seconds: int = 300) -> Callable[[], None]:
    """Continuously renew Telegram typing status until stopped."""
    stop_event = threading.Event()
    chat_id = target or cfg_module.config.notify.telegram.chat_id
    if not chat_id:
        return stop_event.set

    def worker() -> None:
        deadline = time.time() + max_seconds
        while not stop_event.is_set() and time.time() < deadline:
            send_chat_action(target=chat_id)
            stop_event.wait(interval)

    thread = threading.Thread(target=worker, name=f"telegram-typing-{chat_id}", daemon=True)
    thread.start()
    return stop_event.set


def send_photo(photo_path: str, caption: str = "", target: str | None = None, reply_markup: dict[str, Any] | None = None) -> TelegramSendResult:
    tg = cfg_module.config.notify.telegram
    chat_id = target or tg.chat_id
    if not tg.enabled or not tg.bot_token or not chat_id:
        return TelegramSendResult("telegram", False, "telegram not configured")
    try:
        url = f"https://api.telegram.org/bot{tg.bot_token}/sendPhoto"
        payload: dict[str, Any] = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        with open(photo_path, "rb") as f:
            resp = requests.post(url, data=payload, files={"photo": f}, timeout=20)
        data = resp.json() if resp.content else {}
        ok = resp.status_code == 200 and data.get("ok")
        if not ok and "parse entities" in (data.get("description") or "").lower():
            payload.pop("parse_mode", None)
            with open(photo_path, "rb") as f:
                resp = requests.post(url, data=payload, files={"photo": f}, timeout=20)
            data = resp.json() if resp.content else {}
            ok = resp.status_code == 200 and data.get("ok")
        return TelegramSendResult("telegram", bool(ok), data.get("description") or resp.text[:200], data)
    except Exception as e:
        logger.error("Telegram send photo error: %s", e)
        return TelegramSendResult("telegram", False, str(e))


def send_message(text: str, target: str | None = None, reply_markup: dict[str, Any] | None = None) -> TelegramSendResult:
    tg = cfg_module.config.notify.telegram
    chat_id = target or tg.chat_id
    if not tg.enabled or not tg.bot_token or not chat_id:
        return TelegramSendResult("telegram", False, "telegram not configured")
    try:
        url = f"https://api.telegram.org/bot{tg.bot_token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json() if resp.content else {}
        ok = resp.status_code == 200 and data.get("ok")
        # Assistant replies often contain Markdown, raw JSON, or angle brackets.
        # Telegram HTML parsing rejects those. Retry as plain text so a bad parse
        # never looks like a slow/no reply to the user.
        if not ok and "parse entities" in (data.get("description") or "").lower():
            plain_payload = dict(payload)
            plain_payload.pop("parse_mode", None)
            resp = requests.post(url, json=plain_payload, timeout=15)
            data = resp.json() if resp.content else {}
            ok = resp.status_code == 200 and data.get("ok")
        return TelegramSendResult("telegram", bool(ok), data.get("description") or resp.text[:200], data)
    except Exception as e:
        logger.error("Telegram send error: %s", e)
        return TelegramSendResult("telegram", False, str(e))
