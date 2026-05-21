"""QQBot notification channel adapter."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

import app.config as cfg_module

logger = logging.getLogger(__name__)


@dataclass
class QQBotSendResult:
    channel: str
    ok: bool
    message: str = ""
    response: Any = None


_token_cache: dict[str, Any] = {"app_id": "", "token": "", "expires_at": 0.0}


def _plain_text(text: str) -> str:
    return (text or "").replace("<b>", "").replace("</b>", "").replace("<br>", "\n")


def _token() -> str:
    qq = cfg_module.config.notify.qqbot
    now_ms = int(time.time() * 1000)
    if _token_cache.get("app_id") == qq.app_id and _token_cache.get("token") and now_ms < int(_token_cache.get("expires_at") or 0):
        return str(_token_cache["token"])
    resp = requests.post("https://bots.qq.com/app/getAppAccessToken", json={"appId": qq.app_id, "clientSecret": qq.app_secret}, timeout=15)
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(data.get("message") or resp.text[:200])
    expires_in = int(data.get("expires_in") or 7200)
    _token_cache.update({"app_id": qq.app_id, "token": token, "expires_at": now_ms + expires_in * 1000 - 300000})
    return str(token)


def get_token() -> str:
    return _token()


def send_text(text: str, target: str | None = None, group: bool | None = None, msg_id: str | None = None) -> QQBotSendResult:
    qq = cfg_module.config.notify.qqbot
    if not qq.enabled or not qq.app_id or not qq.app_secret:
        return QQBotSendResult("qqbot", False, "qqbot not configured")
    try:
        token = _token()
        is_group = bool(group) if group is not None else bool(qq.group_openid and not target)
        target_id = target or (qq.group_openid if is_group else qq.user_openid)
        if not target_id:
            return QQBotSendResult("qqbot", False, "qqbot target missing")
        path = f"/v2/groups/{target_id}/messages" if is_group else f"/v2/users/{target_id}/messages"
        body: dict[str, Any] = {"content": _plain_text(text), "msg_type": 0, "msg_seq": int(time.time()) % 100000}
        if msg_id:
            body["msg_id"] = msg_id
        resp = requests.post(
            f"https://api.sgroup.qq.com{path}",
            headers={"Authorization": f"QQBot {token}", "Content-Type": "application/json"},
            json=body,
            timeout=15,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or data.get("code"):
            return QQBotSendResult("qqbot", False, data.get("message") or resp.text[:200], data)
        return QQBotSendResult("qqbot", True, "ok", data)
    except Exception as e:
        logger.error("QQBot send error: %s", e)
        return QQBotSendResult("qqbot", False, str(e))
