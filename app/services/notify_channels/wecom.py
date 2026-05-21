"""WeCom notification channel adapter."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

import app.config as cfg_module

logger = logging.getLogger(__name__)


@dataclass
class WeComSendResult:
    channel: str
    ok: bool
    message: str = ""
    response: Any = None


_token_cache: dict[str, Any] = {"key": "", "token": "", "expires_at": 0.0}


def _plain_text(text: str) -> str:
    return (text or "").replace("<b>", "").replace("</b>", "").replace("<br>", "\n")


def _token() -> str:
    wc = cfg_module.config.notify.wecom
    key = f"{wc.corp_id}:{wc.app_secret}"
    now = time.time()
    if _token_cache.get("key") == key and _token_cache.get("token") and now < float(_token_cache.get("expires_at") or 0):
        return str(_token_cache["token"])
    base = (wc.proxy or "https://qyapi.weixin.qq.com").rstrip("/")
    resp = requests.get(f"{base}/cgi-bin/gettoken", params={"corpid": wc.corp_id, "corpsecret": wc.app_secret}, timeout=10)
    data = resp.json()
    if data.get("errcode") != 0 or not data.get("access_token"):
        raise RuntimeError(data.get("errmsg") or resp.text[:200])
    _token_cache.update({"key": key, "token": data["access_token"], "expires_at": now + int(data.get("expires_in") or 7200) - 300})
    return str(data["access_token"])


def _split_text(text: str, *, max_bytes: int = 1800) -> list[str]:
    content = _plain_text(text)
    chunks: list[str] = []
    buf = ""
    for line in content.splitlines() or [content]:
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate.encode("utf-8")) > max_bytes and buf:
            chunks.append(buf)
            buf = line
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return chunks


def send_text(text: str, userid: str | None = None) -> WeComSendResult:
    wc = cfg_module.config.notify.wecom
    if not wc.enabled or not wc.corp_id or not wc.app_secret or not wc.agent_id:
        return WeComSendResult("wecom", False, "wecom not configured")
    try:
        token = _token()
        base = (wc.proxy or "https://qyapi.weixin.qq.com").rstrip("/")
        last = None
        for chunk in _split_text(text):
            resp = requests.post(
                f"{base}/cgi-bin/message/send",
                params={"access_token": token},
                json={"touser": userid or wc.to_user or "@all", "msgtype": "text", "agentid": int(wc.agent_id), "text": {"content": chunk}, "safe": 0},
                timeout=10,
            )
            last = resp.json() if resp.content else {}
            if last.get("errcode") != 0:
                return WeComSendResult("wecom", False, last.get("errmsg") or resp.text[:200], last)
        return WeComSendResult("wecom", True, "ok", last)
    except Exception as e:
        logger.error("WeCom send error: %s", e)
        return WeComSendResult("wecom", False, str(e))
