"""Notification channels and inbound assistant webhooks."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import app.config as cfg_module
from app.db import get_db
from app.services.notify import send_channel, handle_incoming_assistant

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
    return handle_incoming_assistant(
        db,
        channel=req.channel,
        text=req.text,
        user_id=req.user_id,
        target=req.target,
        group=req.group,
        msg_id=req.msg_id,
    )


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
        handle_incoming_assistant(db, channel="wecom", text=msg.content, user_id=msg.from_user, target=msg.from_user, msg_id=msg.msg_id)
        return PlainTextResponse("success")
    # Fallback to generic token-protected JSON/form webhook for proxy mode.
    return await provider_webhook("wecom", request, token=token, db=db)


@router.post("/webhook/{channel}")
async def provider_webhook(channel: str, request: Request, token: str = Query(default=""), db: Session = Depends(get_db)):
    """Best-effort provider webhook normalizer.

    Supported payload shapes:
    - generic: {text,user_id,target,group,msg_id}
    - QQBot gateway event: {type, id, content, author.user_openid, group_openid}
    - WeCom callback after external decrypt/proxy: {Content, FromUserName, MsgId}
    - WeChatBot/iLink-like: {text/content, user_id/from_user/chat_id}
    """
    _check_webhook_token(token)
    try:
        body = await request.json()
    except Exception:
        form = await request.form()
        body = dict(form)

    ch = channel.lower()
    text = str(body.get("text") or body.get("content") or body.get("Content") or body.get("message") or "").strip()
    user_id = str(body.get("user_id") or body.get("userid") or body.get("FromUserName") or body.get("from_user") or "")
    target = str(body.get("target") or body.get("chat_id") or body.get("group_openid") or "")
    group = body.get("group")
    msg_id = str(body.get("msg_id") or body.get("message_id") or body.get("MsgId") or body.get("id") or "")

    if ch == "qqbot":
        event_type = body.get("type") or ""
        content = body.get("content") or ""
        if isinstance(content, str) and content:
            text = content
        author = body.get("author") or {}
        if event_type == "GROUP_AT_MESSAGE_CREATE" or body.get("group_openid"):
            group = True
            target = str(body.get("group_openid") or target or "")
        else:
            group = False
            user_id = str(author.get("user_openid") or user_id or "")
            target = target or user_id
    elif ch in {"wechatbot", "weichatbot"}:
        user_id = user_id or str(body.get("from") or body.get("sender") or "")
        target = target or str(body.get("to") or body.get("room_id") or user_id or "")
    elif ch in {"wecom", "wechat", "wework"}:
        target = target or user_id

    return handle_incoming_assistant(db, channel=ch, text=text, user_id=user_id, target=target, group=group, msg_id=msg_id)
