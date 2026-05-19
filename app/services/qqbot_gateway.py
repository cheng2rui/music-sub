"""QQBot Gateway manager.

Runs a lightweight QQ Open Platform websocket client in a background thread and
forwards C2C / group messages into the notification assistant bridge.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import requests

import app.config as cfg_module
from app.db import SessionLocal
from app.services.notify import handle_incoming_assistant, _qq_token

logger = logging.getLogger(__name__)

INTENT_GROUP_AND_C2C = 1 << 25
_gateway_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_ws_holder: list[Any] = []
_processed_ids: set[str] = set()
_processed_lock = threading.Lock()


def _enabled() -> bool:
    qq = cfg_module.config.notify.qqbot
    return bool(qq.enabled and qq.enable_gateway and qq.app_id and qq.app_secret and qq.assistant_chat)


def _get_gateway_url(token: str) -> str:
    resp = requests.get(
        "https://api.sgroup.qq.com/gateway",
        headers={"Authorization": f"QQBot {token}"},
        timeout=15,
    )
    data = resp.json() if resp.content else {}
    url = data.get("url")
    if not url:
        raise RuntimeError(data.get("message") or resp.text[:200])
    return str(url)


def _dedupe(msg_id: str) -> bool:
    if not msg_id:
        return False
    with _processed_lock:
        if msg_id in _processed_ids:
            return True
        _processed_ids.add(msg_id)
        if len(_processed_ids) > 1000:
            _processed_ids.clear()
        return False


def _handle_dispatch(event_type: str, data: dict[str, Any]) -> None:
    msg_id = str(data.get("id") or "")
    if _dedupe(msg_id):
        return
    content = (data.get("content") or "").strip()
    if not content:
        return
    db = SessionLocal()
    try:
        if event_type == "C2C_MESSAGE_CREATE":
            user_openid = str((data.get("author") or {}).get("user_openid") or "")
            handle_incoming_assistant(db, channel="qqbot", text=content, user_id=user_openid, target=user_openid, group=False, msg_id=msg_id)
        elif event_type == "GROUP_AT_MESSAGE_CREATE":
            group_openid = str(data.get("group_openid") or "")
            member_openid = str((data.get("author") or {}).get("member_openid") or "")
            handle_incoming_assistant(db, channel="qqbot", text=content, user_id=member_openid or group_openid, target=group_openid, group=True, msg_id=msg_id)
    except Exception:
        logger.exception("QQBot Gateway message handling failed")
    finally:
        db.close()


def _run_gateway() -> None:
    try:
        import websocket  # type: ignore
    except Exception as exc:
        logger.error("QQBot Gateway disabled: websocket-client is not installed: %s", exc)
        return

    reconnect_delays = [1, 2, 5, 10, 30, 60]
    attempt = 0
    last_seq: int | None = None
    heartbeat_interval_ms: int | None = None
    heartbeat_timer: threading.Timer | None = None

    def stop_requested() -> bool:
        return bool(_stop_event and _stop_event.is_set())

    def send_heartbeat():
        nonlocal heartbeat_timer
        if stop_requested():
            return
        try:
            if _ws_holder:
                _ws_holder[0].send(json.dumps({"op": 1, "d": last_seq}))
        except Exception as exc:
            logger.debug("QQBot Gateway heartbeat failed: %s", exc)
        if heartbeat_interval_ms and not stop_requested():
            heartbeat_timer = threading.Timer(heartbeat_interval_ms / 1000.0, send_heartbeat)
            heartbeat_timer.daemon = True
            heartbeat_timer.start()

    while not stop_requested():
        try:
            token = _qq_token()
            gateway_url = _get_gateway_url(token)
            logger.info("QQBot Gateway connecting...")

            def on_message(ws, message):
                nonlocal last_seq, heartbeat_interval_ms, heartbeat_timer
                try:
                    payload = json.loads(message)
                except Exception:
                    logger.debug("QQBot Gateway invalid message: %s", str(message)[:200])
                    return
                op = payload.get("op")
                data = payload.get("d") or {}
                event_type = payload.get("t") or ""
                if payload.get("s") is not None:
                    last_seq = payload.get("s")
                if op == 10:
                    heartbeat_interval_ms = int(data.get("heartbeat_interval") or 30000)
                    ws.send(json.dumps({"op": 2, "d": {"token": f"QQBot {token}", "intents": INTENT_GROUP_AND_C2C, "shard": [0, 1]}}))
                    if heartbeat_timer:
                        heartbeat_timer.cancel()
                    heartbeat_timer = threading.Timer(heartbeat_interval_ms / 1000.0, send_heartbeat)
                    heartbeat_timer.daemon = True
                    heartbeat_timer.start()
                elif op == 0:
                    if event_type in {"C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"}:
                        _handle_dispatch(event_type, data)
                    elif event_type == "READY":
                        logger.info("QQBot Gateway ready")
                elif op in {7, 9}:
                    logger.info("QQBot Gateway reconnect requested op=%s", op)
                    try:
                        ws.close()
                    except Exception:
                        pass

            def on_error(ws, error):
                logger.warning("QQBot Gateway websocket error: %s", error)

            def on_close(ws, code, msg):
                nonlocal heartbeat_timer
                logger.info("QQBot Gateway closed: %s %s", code, msg)
                if heartbeat_timer:
                    heartbeat_timer.cancel()
                    heartbeat_timer = None
                _ws_holder.clear()

            ws = websocket.WebSocketApp(gateway_url, on_message=on_message, on_error=on_error, on_close=on_close)
            _ws_holder.clear()
            _ws_holder.append(ws)
            ws.run_forever(ping_interval=None, ping_timeout=None, skip_utf8_validation=True)
        except Exception as exc:
            logger.warning("QQBot Gateway connection failed: %s", exc)

        if stop_requested():
            break
        delay = reconnect_delays[min(attempt, len(reconnect_delays) - 1)]
        attempt += 1
        for _ in range(delay * 10):
            if stop_requested():
                break
            time.sleep(0.1)

    if heartbeat_timer:
        heartbeat_timer.cancel()
    logger.info("QQBot Gateway stopped")


def start_qqbot_gateway() -> None:
    global _gateway_thread, _stop_event
    if not _enabled():
        return
    if _gateway_thread and _gateway_thread.is_alive():
        return
    _stop_event = threading.Event()
    _gateway_thread = threading.Thread(target=_run_gateway, daemon=True, name="qqbot-gateway")
    _gateway_thread.start()
    logger.info("QQBot Gateway thread started")


def stop_qqbot_gateway() -> None:
    global _gateway_thread, _stop_event
    if _stop_event:
        _stop_event.set()
    try:
        if _ws_holder:
            _ws_holder[0].close()
    except Exception:
        pass
    if _gateway_thread and _gateway_thread.is_alive():
        _gateway_thread.join(timeout=10)
    _gateway_thread = None
    _stop_event = None


def restart_qqbot_gateway() -> None:
    stop_qqbot_gateway()
    start_qqbot_gateway()


def qqbot_gateway_status() -> dict[str, Any]:
    return {"enabled": _enabled(), "running": bool(_gateway_thread and _gateway_thread.is_alive())}
