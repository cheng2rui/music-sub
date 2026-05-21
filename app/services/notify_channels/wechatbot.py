"""WeChatBot / WeChat Claw notification channel adapter."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

import app.config as cfg_module

logger = logging.getLogger(__name__)


@dataclass
class WeChatBotSendResult:
    channel: str
    ok: bool
    message: str = ""
    response: Any = None


def _plain_text(text: str) -> str:
    return (text or "").replace("<b>", "").replace("</b>", "").replace("<br>", "\n")


def send_text(text: str, target: str | None = None) -> WeChatBotSendResult:
    wb = cfg_module.config.notify.wechatbot
    if not wb.enabled:
        return WeChatBotSendResult("wechatbot", False, "wechatbot not enabled")
    if wb.enable_claw:
        try:
            from app.services.wechatclaw import load_state, send_text as claw_send_text

            target_id = target or wb.claw_default_target or ""
            if not target_id:
                targets = load_state().get("known_targets") or {}
                if targets:
                    target_id = sorted(targets.values(), key=lambda x: x.get("last_active") or 0, reverse=True)[0].get("userid") or ""
            if not target_id:
                return WeChatBotSendResult("wechatbot", False, "wechat claw target missing")
            ok = claw_send_text(target_id, _plain_text(text))
            return WeChatBotSendResult("wechatbot", ok, "ok" if ok else "wechat claw send failed")
        except Exception as e:
            logger.error("WeChat Claw send error: %s", e)
            return WeChatBotSendResult("wechatbot", False, str(e))
    if not wb.webhook_url:
        return WeChatBotSendResult("wechatbot", False, "wechatbot webhook_url not configured")
    try:
        payload: dict[str, Any] = {"text": _plain_text(text)}
        if target:
            payload["target"] = target
        if wb.token:
            payload["token"] = wb.token
        resp = requests.post(wb.webhook_url, json=payload, timeout=15)
        ok = 200 <= resp.status_code < 300
        data = None
        try:
            data = resp.json()
        except Exception:
            data = resp.text[:300]
        return WeChatBotSendResult("wechatbot", ok, "ok" if ok else str(data)[:200], data)
    except Exception as e:
        logger.error("WeChatBot send error: %s", e)
        return WeChatBotSendResult("wechatbot", False, str(e))
