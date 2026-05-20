"""Telegram getUpdates polling runtime for private/NAS deployments.

Telegram webhooks require a public HTTPS endpoint. Polling keeps inbound
Assistant chat working when Music Sub only has outbound internet access.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

import app.config as cfg_module
from app.db import SessionLocal
from app.services.incoming_queue import enqueue_incoming_message
from app.services.notify import log_notify_event, normalize_incoming_message

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_thread: threading.Thread | None = None
_status: dict[str, Any] = {
    "running": False,
    "enabled": False,
    "last_update_id": None,
    "last_error": "",
    "last_message_at": None,
    "webhook_url": "",
}


def _redact_error(exc: Exception | str) -> str:
    text = str(exc)
    token = cfg_module.config.notify.telegram.bot_token
    if token:
        text = text.replace(token, token[:6] + "…" + token[-4:])
    return text


def _telegram_api(method: str, payload: dict[str, Any] | None = None, timeout: int = 35) -> dict[str, Any]:
    tg = cfg_module.config.notify.telegram
    resp = requests.post(f"https://api.telegram.org/bot{tg.bot_token}/{method}", json=payload or {}, timeout=timeout)
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400 or data.get("ok") is False:
        raise RuntimeError(data.get("description") or resp.text[:300])
    return data


def _poll_loop() -> None:
    tg = cfg_module.config.notify.telegram
    offset: int | None = None
    _status.update({"running": True, "enabled": True, "last_error": ""})
    logger.info("Telegram polling started")
    try:
        try:
            info = _telegram_api("getWebhookInfo", timeout=15).get("result") or {}
            webhook_url = info.get("url") or ""
            _status["webhook_url"] = webhook_url
            if webhook_url:
                logger.info("Telegram polling disabled because webhook is configured: %s", webhook_url)
                _status.update({"running": False, "last_error": "webhook configured; polling skipped"})
                return
        except Exception as exc:
            logger.warning("Telegram getWebhookInfo before polling failed: %s", _redact_error(exc))
            _status["last_error"] = _redact_error(exc)[:300]

        while not _stop_event.is_set():
            try:
                current = cfg_module.config.notify.telegram
                if not (current.enabled and current.bot_token and current.assistant_chat and getattr(current, "enable_polling", False)):
                    time.sleep(2)
                    continue
                payload: dict[str, Any] = {
                    "timeout": max(1, min(int(getattr(current, "polling_timeout", 25) or 25), 50)),
                    "allowed_updates": ["message", "edited_message", "callback_query"],
                }
                if offset is not None:
                    payload["offset"] = offset
                data = _telegram_api("getUpdates", payload, timeout=payload["timeout"] + 10)
                updates = data.get("result") or []
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                        _status["last_update_id"] = update_id
                    db = SessionLocal()
                    try:
                        incoming = normalize_incoming_message("telegram", update)
                        _status["last_message_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                        enqueue_incoming_message(incoming)
                    except Exception as exc:
                        logger.exception("Telegram polling inbound enqueue failed")
                        _status["last_error"] = _redact_error(exc)[:300]
                        try:
                            log_notify_event(
                                channel="telegram",
                                direction="inbound",
                                status="error",
                                message=f"polling inbound enqueue failed: {str(exc)[:200]}",
                                raw=update,
                                db=db,
                            )
                        except Exception:
                            pass
                    finally:
                        db.close()
                _status["last_error"] = ""
            except requests.exceptions.ReadTimeout:
                continue
            except Exception as exc:
                logger.warning("Telegram polling error: %s", _redact_error(exc))
                _status["last_error"] = _redact_error(exc)[:300]
                _stop_event.wait(5)
    finally:
        _status["running"] = False
        logger.info("Telegram polling stopped")


def start_telegram_polling() -> None:
    global _thread
    tg = cfg_module.config.notify.telegram
    _status["enabled"] = bool(tg.enabled and tg.bot_token and tg.assistant_chat and getattr(tg, "enable_polling", False))
    if not _status["enabled"]:
        return
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_poll_loop, name="telegram-polling", daemon=True)
    _thread.start()


def stop_telegram_polling() -> None:
    global _thread
    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
    _thread = None
    _status["running"] = False


def restart_telegram_polling() -> None:
    stop_telegram_polling()
    start_telegram_polling()


def telegram_polling_status() -> dict[str, Any]:
    status = dict(_status)
    tg = cfg_module.config.notify.telegram
    status["enabled"] = bool(tg.enabled and tg.bot_token and tg.assistant_chat and getattr(tg, "enable_polling", False))
    status["thread_alive"] = bool(_thread and _thread.is_alive())
    return status
