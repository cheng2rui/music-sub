"""Notification channels and inbound assistant webhooks."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import requests

import app.config as cfg_module
from app.db import get_db
from app.models import NotifyEvent
from app.services.notify import IncomingMessage, normalize_incoming_message, send_channel, handle_incoming_message

router = APIRouter()


class SendRequest(BaseModel):
    channel: str
    text: str
    target: str | None = None
    group: bool | None = None
    msg_id: str | None = None


class IncomingRequest(BaseModel):
    channel: str
    text: str = ""
    user_id: str = ""
    target: str = ""
    group: bool | None = None
    msg_id: str | None = None
    raw: dict[str, Any] = {}




def _telegram_webhook_url() -> str:
    token = cfg_module.config.notify.webhook_token
    if not token:
        return ""
    return f"/api/notify/webhook/telegram?token={token}"


def _telegram_api(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    tg = cfg_module.config.notify.telegram
    if not tg.bot_token or "***" in tg.bot_token:
        raise HTTPException(status_code=400, detail="telegram bot_token is not configured")
    try:
        resp = requests.post(f"https://api.telegram.org/bot{tg.bot_token}/{method}", json=payload or {}, timeout=15)
        data = resp.json() if resp.content else {}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"telegram api error: {exc}")
    if resp.status_code >= 400 or data.get("ok") is False:
        raise HTTPException(status_code=502, detail=data.get("description") or resp.text[:300])
    return data


def _check_webhook_token(token: str = ""):
    expected = cfg_module.config.notify.webhook_token
    # Webhook endpoints are public by design, so require an explicit token
    # before accepting inbound assistant messages.
    if not expected:
        raise HTTPException(status_code=403, detail="webhook token is not configured")
    if token != expected:
        raise HTTPException(status_code=403, detail="invalid webhook token")


@router.post("/send")
def send(req: SendRequest):
    result = send_channel(req.channel, req.text, target=req.target, group=req.group, msg_id=req.msg_id)
    return result.__dict__


@router.post("/test/{channel}")
def test_channel(channel: str):
    result = send_channel(channel, "🎵 Music Sub 通知渠道测试成功")
    return result.__dict__


@router.get("/events")
def notify_events(limit: int = Query(default=50, ge=1, le=200), channel: str = Query(default=""), db: Session = Depends(get_db)):
    q = db.query(NotifyEvent)
    if channel:
        q = q.filter(NotifyEvent.channel == channel.lower())
    rows = q.order_by(NotifyEvent.id.desc()).limit(limit).all()
    return {
        "items": [
            {
                "id": r.id,
                "channel": r.channel,
                "direction": r.direction,
                "event": r.event,
                "user_id": r.user_id,
                "target": r.target,
                "status": r.status,
                "message": r.message,
                "text_preview": r.text_preview,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/status")
def notify_status(db: Session = Depends(get_db)):
    cfg = cfg_module.config.notify
    latest = db.query(NotifyEvent).order_by(NotifyEvent.id.desc()).limit(50).all()
    by_channel: dict[str, dict[str, Any]] = {}
    for name in ("telegram", "wecom", "qqbot", "wechatbot"):
        ch_cfg = getattr(cfg, name)
        by_channel[name] = {
            "enabled": bool(getattr(ch_cfg, "enabled", False)),
            "assistant_chat": bool(getattr(ch_cfg, "assistant_chat", True)),
            "last_inbound": None,
            "last_outbound": None,
            "last_error": None,
        }
    for row in latest:
        bucket = by_channel.setdefault(row.channel, {"enabled": False, "assistant_chat": True, "last_inbound": None, "last_outbound": None, "last_error": None})
        brief = {
            "id": row.id,
            "status": row.status,
            "message": row.message,
            "text_preview": row.text_preview,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        if row.status == "error" and not bucket.get("last_error"):
            bucket["last_error"] = brief
        if row.direction == "inbound" and not bucket.get("last_inbound"):
            bucket["last_inbound"] = brief
        if row.direction == "outbound" and not bucket.get("last_outbound"):
            bucket["last_outbound"] = brief
    try:
        from app.services.qqbot_gateway import qqbot_gateway_status
        by_channel["qqbot"]["gateway"] = qqbot_gateway_status()
    except Exception as exc:
        by_channel["qqbot"]["gateway"] = {"error": str(exc)}
    try:
        from app.services.wechatclaw import get_status
        by_channel["wechatbot"]["claw"] = get_status()
    except Exception as exc:
        by_channel["wechatbot"]["claw"] = {"error": str(exc)}
    return {"channels": by_channel}




@router.get("/telegram/webhook")
def telegram_webhook_info():
    """Return current Telegram webhook state and Music Sub recommended URL path."""
    tg = cfg_module.config.notify.telegram
    recommended = _telegram_webhook_url()
    if not tg.bot_token or "***" in tg.bot_token:
        return {"ok": False, "configured": False, "recommended_path": recommended, "message": "telegram bot_token is not configured"}
    data = _telegram_api("getWebhookInfo")
    return {"ok": True, "configured": True, "recommended_path": recommended, "telegram": data.get("result") or data}


@router.post("/telegram/webhook")
def telegram_set_webhook(base_url: str = Body(default="", embed=True), drop_pending_updates: bool = Body(default=False, embed=True)):
    """Set Telegram webhook to this Music Sub callback URL.

    `base_url` should be the public origin, e.g. https://music.example.com.
    """
    if not cfg_module.config.notify.webhook_token:
        raise HTTPException(status_code=400, detail="notify webhook_token is not configured")
    origin = (base_url or "").strip().rstrip("/")
    if not origin.startswith("https://"):
        raise HTTPException(status_code=400, detail="base_url must be a public https origin")
    url = origin + _telegram_webhook_url()
    data = _telegram_api("setWebhook", {"url": url, "drop_pending_updates": bool(drop_pending_updates)})
    return {"ok": True, "url": url, "telegram": data.get("result") if "result" in data else data}


@router.delete("/telegram/webhook")
def telegram_delete_webhook(drop_pending_updates: bool = Query(default=False)):
    data = _telegram_api("deleteWebhook", {"drop_pending_updates": bool(drop_pending_updates)})
    return {"ok": True, "telegram": data.get("result") if "result" in data else data}


@router.get("/wechatclaw/status")
def wechatclaw_state(refresh: bool = False, auto_qrcode: bool = False):
    from app.services.wechatclaw import get_status
    return get_status(refresh=refresh, auto_qrcode=auto_qrcode)


@router.post("/wechatclaw/qrcode")
def wechatclaw_qrcode():
    from app.services.wechatclaw import get_qrcode
    return get_qrcode()


@router.post("/wechatclaw/restart")
def wechatclaw_restart():
    from app.services.wechatclaw import restart_wechatclaw_polling, get_status
    restart_wechatclaw_polling()
    return get_status()


@router.get("/wechatclaw/config")
def wechatclaw_config():
    from app.services.wechatclaw import get_config
    return get_config()


@router.post("/wechatclaw/logout")
def wechatclaw_logout():
    from app.services.wechatclaw import logout
    return logout()


@router.get("/qqbot/gateway/status")
def qqbot_gateway_state():
    from app.services.qqbot_gateway import qqbot_gateway_status
    return qqbot_gateway_status()


@router.post("/qqbot/gateway/restart")
def qqbot_gateway_restart():
    from app.services.qqbot_gateway import restart_qqbot_gateway, qqbot_gateway_status
    restart_qqbot_gateway()
    return qqbot_gateway_status()


@router.post("/incoming")
def incoming(req: IncomingRequest, token: str = Query(default=""), db: Session = Depends(get_db)):
    _check_webhook_token(token)
    return handle_incoming_message(db, IncomingMessage(
        channel=req.channel,
        text=req.text,
        user_id=req.user_id,
        target=req.target,
        group=req.group,
        msg_id=req.msg_id or "",
        raw=req.raw,
    ))


@router.get("/webhook/wecom")
def wecom_verify(
    msg_signature: str = Query(default=""),
    timestamp: str = Query(default=""),
    nonce: str = Query(default=""),
    echostr: str = Query(default=""),
):
    """Native WeCom URL verification endpoint."""
    from app.services.wecom_crypto import verify_url, WeComCryptoError
    wc = cfg_module.config.notify.wecom
    if not wc.token or not wc.encoding_aes_key or not wc.corp_id:
        raise HTTPException(status_code=400, detail="wecom token/encoding_aes_key/corp_id not configured")
    try:
        plain = verify_url(
            token=wc.token,
            encoding_aes_key=wc.encoding_aes_key,
            receive_id=wc.corp_id,
            msg_signature=msg_signature,
            timestamp=timestamp,
            nonce=nonce,
            echostr=echostr,
        )
        return PlainTextResponse(plain)
    except WeComCryptoError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/webhook/wecom")
async def wecom_native_webhook(
    request: Request,
    msg_signature: str = Query(default=""),
    timestamp: str = Query(default=""),
    nonce: str = Query(default=""),
    token: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Native encrypted WeCom application callback."""
    from app.services.wecom_crypto import decrypt_message, parse_plain_message, WeComCryptoError
    wc = cfg_module.config.notify.wecom
    if wc.token and wc.encoding_aes_key and wc.corp_id and msg_signature and timestamp and nonce:
        body = (await request.body()).decode("utf-8", errors="replace")
        try:
            plain_xml = decrypt_message(
                token=wc.token,
                encoding_aes_key=wc.encoding_aes_key,
                receive_id=wc.corp_id,
                msg_signature=msg_signature,
                timestamp=timestamp,
                nonce=nonce,
                body=body,
            )
            msg = parse_plain_message(plain_xml)
        except WeComCryptoError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        if not msg.content:
            return PlainTextResponse("success")
        handle_incoming_message(db, IncomingMessage(channel="wecom", text=msg.content, user_id=msg.from_user, target=msg.from_user, msg_id=msg.msg_id, source="wecom-native", raw={"plain_xml": plain_xml}))
        return PlainTextResponse("success")
    # Fallback to generic token-protected JSON/form webhook for proxy mode.
    return await provider_webhook("wecom", request, token=token, db=db)


@router.post("/webhook/{channel}")
async def provider_webhook(channel: str, request: Request, token: str = Query(default=""), db: Session = Depends(get_db)):
    """Provider webhook endpoint.

    Raw provider payloads are parsed into `IncomingMessage` first, then the
    assistant pipeline handles one stable shape. This mirrors MoviePilot's
    message-parser pattern and keeps future image/audio/button support isolated
    in provider parsers.
    """
    _check_webhook_token(token)
    try:
        body = await request.json()
    except Exception:
        form = await request.form()
        body = dict(form)

    incoming = normalize_incoming_message(channel, body)
    return handle_incoming_message(db, incoming)
