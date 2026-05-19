"""Notification channels and inbound assistant webhooks."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
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
