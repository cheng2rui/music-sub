"""WeChat Claw / iLink client and polling manager.

A compact Music Sub adaptation of MoviePilot's WechatClawBot: QR login state,
long polling, text send, and inbound messages bridged into Assistant.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import requests

import app.config as cfg_module
from app.db import SessionLocal
from app.services.notify import handle_incoming_assistant

logger = logging.getLogger(__name__)
STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "wechatclaw_state.json"
_state_lock = threading.Lock()
_poll_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _cfg():
    return cfg_module.config.notify.wechatbot


def _base_url() -> str:
    return (_cfg().claw_base_url or "https://ilinkai.weixin.qq.com").rstrip("/")


def _headers(auth: bool = True) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "MusicSub-WeChatClaw/1.0"}
    state = load_state()
    token = state.get("bot_token")
    if auth and token:
        headers["AuthorizationType"] = "ilink_bot_token"
        headers["Authorization"] = f"Bearer {token}"
        headers["X-WECHAT-UIN"] = base64.b64encode(str(int(time.time() * 1000) % 2**32).encode()).decode()
    return headers


def _json(resp: requests.Response | None) -> dict[str, Any]:
    if not resp:
        return {}
    try:
        return resp.json() or {}
    except Exception:
        try:
            return json.loads(resp.text or "{}")
        except Exception:
            return {}


def _ok(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    for key in ("errcode", "code", "ret"):
        if key in payload:
            try:
                return int(str(payload.get(key))) == 0
            except Exception:
                return str(payload.get(key)).lower() in {"ok", "success", "succeed", "true"}
    if isinstance(payload.get("success"), bool):
        return payload["success"]
    return True


def _normalize_qrcode_url(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower.startswith("data:image/"):
        return raw
    if lower.startswith("//"):
        return "https:" + raw
    if len(raw) >= 128 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", raw):
        return "data:image/png;base64," + raw
    return raw


def _find_first(data: Any, keys: list[str], depth: int = 5) -> Any:
    if depth < 0 or data is None:
        return None
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return value
        for value in data.values():
            found = _find_first(value, keys, depth - 1)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_first(value, keys, depth - 1)
            if found not in (None, ""):
                return found
    return None


def _find_first_list(data: Any, keys: list[str], depth: int = 5) -> list[Any] | None:
    if depth < 0 or data is None:
        return None
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
        for value in data.values():
            found = _find_first_list(value, keys, depth - 1)
            if found is not None:
                return found
    elif isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data):
            return data
        for value in data:
            found = _find_first_list(value, keys, depth - 1)
            if found is not None:
                return found
    return None


def load_state() -> dict[str, Any]:
    with _state_lock:
        try:
            if STATE_PATH.exists():
                data = json.loads(STATE_PATH.read_text("utf-8"))
                if isinstance(data, dict):
                    data.setdefault("qrcode", {})
                    data.setdefault("known_targets", {})
                    data.setdefault("context_tokens", {})
                    return data
        except Exception as exc:
            logger.warning("load wechat claw state failed: %s", exc)
        return {"bot_token": None, "account_id": None, "sync_buf": None, "qrcode": {}, "known_targets": {}, "context_tokens": {}}


def save_state(**updates) -> dict[str, Any]:
    with _state_lock:
        state = {}
        try:
            if STATE_PATH.exists():
                state = json.loads(STATE_PATH.read_text("utf-8")) or {}
        except Exception:
            state = {}
        state.update(updates)
        state.setdefault("qrcode", {})
        state.setdefault("known_targets", {})
        state.setdefault("context_tokens", {})
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
        return state


def clear_state() -> None:
    save_state(bot_token=None, account_id=None, sync_buf=None, qrcode={}, context_tokens={})


def get_qrcode() -> dict[str, Any]:
    resp = requests.get(f"{_base_url()}/ilink/bot/get_bot_qrcode?bot_type=3", headers=_headers(False), timeout=20)
    payload = _json(resp)
    data = payload.get("data") or payload.get("result") or payload
    qrcode = data.get("qrcode") or data.get("qr_code") or data.get("qrcode_id") or data.get("ticket")
    url = _normalize_qrcode_url(data.get("qrcode_url") or data.get("url") or data.get("qrcodeUrl") or data.get("qr_url") or data.get("qrcode_img_content") or data.get("qrcode_img_url") or data.get("qr_img"))
    if not url and qrcode:
        url = f"https://liteapp.weixin.qq.com/q/7GiQu1?qrcode={qrcode}&bot_type=3"
    qrcode_state = {"qrcode": qrcode, "qrcode_url": url, "status": "waiting", "updated_at": int(time.time())}
    save_state(qrcode=qrcode_state)
    return {"success": _ok(payload) and bool(qrcode or url), **qrcode_state, "message": payload.get("errmsg") or payload.get("message")}


def refresh_qrcode_status() -> dict[str, Any]:
    state = load_state()
    qrcode = (state.get("qrcode") or {}).get("qrcode")
    if not qrcode:
        return get_status()
    resp = requests.get(f"{_base_url()}/ilink/bot/get_qrcode_status", params={"qrcode": qrcode}, headers=_headers(False), timeout=20)
    payload = _json(resp)
    data = payload.get("data") or payload.get("result") or payload
    token = data.get("bot_token") or data.get("token") or data.get("access_token") or _find_first(data, ["bot_token", "access_token", "token", "jwt", "auth_token"])
    account_id = data.get("account_id") or data.get("ilink_bot_id") or data.get("wxid") or data.get("uid") or data.get("user_id") or _find_first(data, ["account_id", "ilink_bot_id", "wxid", "uid", "user_id"])
    status = str(data.get("status") or data.get("state") or payload.get("status") or payload.get("state") or _find_first(data, ["status", "state", "scan_status"]) or "waiting").lower()
    qrcode_state = dict(state.get("qrcode") or {})
    qrcode_state.update({"status": status, "updated_at": int(time.time())})
    url = _normalize_qrcode_url(data.get("qrcode_url") or data.get("url") or data.get("qrcodeUrl") or data.get("qr_url"))
    if url:
        qrcode_state["qrcode_url"] = url
    updates = {"qrcode": qrcode_state}
    if token:
        updates.update({"bot_token": token, "account_id": str(account_id or "") or None, "sync_buf": None})
    save_state(**updates)
    if token:
        start_wechatclaw_polling()
    return get_status()


def get_status(refresh: bool = False, auto_qrcode: bool = False) -> dict[str, Any]:
    state = load_state()
    qrcode = state.get("qrcode") or {}
    if auto_qrcode and not state.get("bot_token") and not qrcode.get("qrcode"):
        get_qrcode()
        state = load_state()
        qrcode = state.get("qrcode") or {}
    if refresh and not state.get("bot_token") and qrcode.get("qrcode"):
        return refresh_qrcode_status()
    return {
        "enabled": bool(_cfg().enabled and _cfg().enable_claw),
        "running": bool(_poll_thread and _poll_thread.is_alive()),
        "connected": bool(state.get("bot_token")),
        "account_id": state.get("account_id"),
        "qrcode": qrcode.get("qrcode"),
        "qrcode_url": qrcode.get("qrcode_url"),
        "qrcode_status": qrcode.get("status"),
        "qrcode_updated_at": qrcode.get("updated_at"),
        "known_targets": sorted((state.get("known_targets") or {}).values(), key=lambda x: x.get("last_active") or 0, reverse=True),
    }


def _with_base(body: dict[str, Any]) -> dict[str, Any]:
    payload = dict(body or {})
    payload.setdefault("base_info", {})
    payload["base_info"].setdefault("channel_version", "1.0.2")
    return payload


def send_text(to_user: str, text: str, context_token: str | None = None) -> bool:
    state = load_state()
    token = state.get("bot_token")
    if not token:
        return False
    candidates = [str(to_user)]
    if str(to_user).endswith("@im.wechat"):
        candidates.append(str(to_user)[:-10])
    elif "@" not in str(to_user):
        candidates.append(str(to_user) + "@im.wechat")
    payloads = []
    for user in dict.fromkeys(candidates):
        msg = {"from_user_id": str(state.get("account_id") or ""), "to_user_id": user, "client_id": f"ms-{int(time.time()*1000)}", "message_type": 2, "message_state": 2, "item_list": [{"type": 1, "text_item": {"text": text}}]}
        if context_token:
            msg["context_token"] = context_token
        payloads.extend([{"msg": msg}, {"to_user": user, "msg_type": "text", "text": {"content": text}}, {"to_user": user, "msg_type": "text", "text": text}, {"to": user, "type": "text", "content": text}])
    for payload in payloads:
        try:
            resp = requests.post(f"{_base_url()}/ilink/bot/sendmessage", json=_with_base(payload), headers=_headers(True), timeout=20)
            data = _json(resp)
            if 200 <= resp.status_code < 300 and not str(_find_first(data, ["errmsg", "error", "detail"]) or "").lower() not in {"", "ok", "success"}:
                return True
            if _ok(data):
                return True
        except Exception as exc:
            logger.debug("wechat claw send candidate failed: %s", exc)
    return False


def _parse_message(item: dict[str, Any]) -> dict[str, str] | None:
    msg = item
    for key in ["message", "msg", "event", "payload", "data", "body"]:
        if isinstance(msg, dict) and isinstance(msg.get(key), dict):
            msg = msg[key]
            break
    user = _find_first(msg, ["user_id", "from_user_id", "sender_id", "from", "from_user", "wxid", "uid"]) or _find_first(item, ["user_id", "from_user_id", "sender_id", "from", "from_user", "wxid", "uid"])
    text = _find_first(msg, ["content", "text", "message", "msg", "body", "msg_content", "msgContent"])
    if isinstance(text, dict):
        text = _find_first(text, ["content", "text", "value", "message"])
    if not text and isinstance(msg.get("item_list"), list):
        parts = []
        for part in msg.get("item_list") or []:
            if isinstance(part, dict):
                parts.append(str(_find_first(part, ["text", "content", "value"]) or ""))
        text = "\n".join([p for p in parts if p])
    if not user or not text:
        return None
    return {"user_id": str(user), "text": str(text).strip(), "message_id": str(_find_first(msg, ["message_id", "msg_id", "id", "client_msg_id", "msgId", "seq"]) or _find_first(item, ["message_id", "msg_id", "id", "client_msg_id", "msgId", "seq"]) or ""), "context_token": str(_find_first(msg, ["context_token", "contextToken"]) or "")}


def _poll_once() -> tuple[list[dict[str, str]], str | None, dict[str, Any]]:
    state = load_state()
    if not state.get("bot_token"):
        return [], state.get("sync_buf"), {"success": False, "message": "not logged in"}
    resp = requests.post(f"{_base_url()}/ilink/bot/getupdates", json=_with_base({"get_updates_buf": state.get("sync_buf") or ""}), headers=_headers(True), timeout=max(int(_cfg().claw_poll_timeout or 25), 10) + 10)
    payload = _json(resp)
    if not payload:
        return [], state.get("sync_buf"), {"success": False, "message": "empty response"}
    items = _find_first_list(payload, ["msgs", "messages", "updates", "items", "list"]) or []
    sync_buf = payload.get("get_updates_buf") if "get_updates_buf" in payload else payload.get("sync_buf") or payload.get("syncBuf")
    parsed = [m for m in (_parse_message(x) for x in items if isinstance(x, dict)) if m]
    if sync_buf is not None:
        save_state(sync_buf=str(sync_buf))
    return parsed, sync_buf, {"success": True, "count": len(items), "parsed": len(parsed)}


def _remember_target(user_id: str, context_token: str = "") -> None:
    state = load_state()
    targets = state.setdefault("known_targets", {})
    targets[user_id] = {"userid": user_id, "username": user_id, "last_active": int(time.time())}
    tokens = state.setdefault("context_tokens", {})
    if context_token:
        tokens[user_id] = context_token
    save_state(known_targets=targets, context_tokens=tokens)


def _poll_loop() -> None:
    failures = 0
    backoff = [1, 2, 5, 10, 30]
    while _stop_event and not _stop_event.is_set() and load_state().get("bot_token"):
        try:
            messages, _, result = _poll_once()
            if not result.get("success"):
                raise RuntimeError(result.get("message") or "poll failed")
            for msg in messages:
                _remember_target(msg["user_id"], msg.get("context_token") or "")
                db = SessionLocal()
                try:
                    handle_incoming_assistant(db, channel="wechatbot", text=msg["text"], user_id=msg["user_id"], target=msg["user_id"], msg_id=msg.get("message_id") or None)
                finally:
                    db.close()
            failures = 0
        except Exception as exc:
            failures += 1
            delay = backoff[min(failures - 1, len(backoff) - 1)]
            logger.warning("WeChat Claw polling failed, retry in %ss: %s", delay, exc)
            if failures >= 10:
                clear_state()
                break
            if _stop_event:
                _stop_event.wait(delay)


def start_wechatclaw_polling() -> None:
    global _poll_thread, _stop_event
    if not (_cfg().enabled and _cfg().enable_claw and _cfg().assistant_chat and load_state().get("bot_token")):
        return
    if _poll_thread and _poll_thread.is_alive():
        return
    _stop_event = threading.Event()
    _poll_thread = threading.Thread(target=_poll_loop, daemon=True, name="wechatclaw-poll")
    _poll_thread.start()


def stop_wechatclaw_polling() -> None:
    global _poll_thread, _stop_event
    if _stop_event:
        _stop_event.set()
    if _poll_thread and _poll_thread.is_alive():
        _poll_thread.join(timeout=10)
    _poll_thread = None
    _stop_event = None


def restart_wechatclaw_polling() -> None:
    stop_wechatclaw_polling()
    start_wechatclaw_polling()


def logout() -> dict[str, Any]:
    stop_wechatclaw_polling()
    clear_state()
    return {"success": True, "message": "已退出微信 Claw 登录"}
