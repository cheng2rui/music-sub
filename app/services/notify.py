"""Multi-channel notification service.

Inspired by MoviePilot's message modules, this module keeps Music Sub's first
implementation intentionally small: one unified outbound API and one normalized
inbound path that can forward user messages to the built-in assistant.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import requests
from sqlalchemy.orm import Session

import app.config as cfg_module
from app.db import SessionLocal
from app.models import AssistantAction, AssistantConversation, NotifyEvent

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    channel: str
    ok: bool
    message: str = ""
    response: Any = None


@dataclass
class NotifyAction:
    label: str
    command: str
    style: str = "default"


def telegram_inline_keyboard(actions: list[NotifyAction] | None) -> dict[str, Any] | None:
    if not actions:
        return None
    row = []
    for action in actions[:6]:
        label = (action.label or action.command or "Action")[:64]
        command = (action.command or "")[:64]
        if not command:
            continue
        row.append({"text": label, "callback_data": f"ms_cmd:{command}"})
    if not row:
        return None
    return {"inline_keyboard": [row[i:i + 2] for i in range(0, len(row), 2)]}


@dataclass
class IncomingMessage:
    """Normalized inbound chat message.

    This is intentionally close to MoviePilot's CommingMessage idea: provider
    webhooks are parsed once into a stable shape, then the assistant pipeline no
    longer needs to know each platform's raw payload format.
    """
    channel: str
    text: str = ""
    user_id: str = ""
    username: str = ""
    target: str = ""
    group: bool | None = None
    msg_id: str = ""
    chat_id: str = ""
    source: str = ""
    raw: Any = None

    def meta(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "chat_id": self.chat_id,
            "source": self.source,
            "group": self.group,
            "msg_id": self.msg_id,
        }


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _pick_text(*values: Any) -> str:
    for value in values:
        text = _as_str(value)
        if text:
            return text
    return ""


def normalize_incoming_message(channel: str, body: dict[str, Any] | Any) -> IncomingMessage:
    """Normalize common provider webhook payloads into IncomingMessage.

    Supported today:
    - generic JSON/form: {channel,text,user_id,target,group,msg_id}
    - Telegram Update: message / edited_message / callback_query
    - QQBot event: content + author.user_openid / group_openid
    - WeCom decrypted/proxy payload: Content + FromUserName + MsgId
    - WeChatBot/iLink-like payload: text/content + from/sender/chat_id
    """
    raw = body
    if not isinstance(body, dict):
        body = {}
    ch = (channel or body.get("channel") or "").lower()

    # Telegram Bot API update.
    if ch == "telegram":
        update = body
        callback = update.get("callback_query") if isinstance(update.get("callback_query"), dict) else None
        if callback:
            user = callback.get("from") or {}
            msg = callback.get("message") or {}
            chat = msg.get("chat") or {}
            data = _as_str(callback.get("data"))
            text = f"CALLBACK:{data}" if data else _pick_text(callback.get("message"), callback.get("text"))
            if data == "ms_confirm":
                text = "确认"
            elif data == "ms_cancel":
                text = "取消"
            elif data.startswith("ms_cmd:"):
                text = data[len("ms_cmd:"):].strip()
            return IncomingMessage(
                channel="telegram",
                text=text,
                user_id=_as_str(user.get("id")),
                username=_pick_text(user.get("username"), user.get("first_name"), user.get("last_name")),
                target=_as_str(chat.get("id") or user.get("id")),
                chat_id=_as_str(chat.get("id")),
                group=(chat.get("type") not in {None, "private"}),
                msg_id=_as_str(msg.get("message_id") or callback.get("id")),
                source="telegram",
                raw=raw,
            )
        msg = update.get("message") or update.get("edited_message") or update.get("channel_post") or update
        if isinstance(msg, dict):
            user = msg.get("from") or msg.get("sender_chat") or {}
            chat = msg.get("chat") or {}
            text = _pick_text(msg.get("text"), msg.get("caption"))
            return IncomingMessage(
                channel="telegram",
                text=text,
                user_id=_as_str(user.get("id") or chat.get("id")),
                username=_pick_text(user.get("username"), user.get("first_name"), user.get("title")),
                target=_as_str(chat.get("id") or user.get("id")),
                chat_id=_as_str(chat.get("id")),
                group=(chat.get("type") not in {None, "private"}),
                msg_id=_as_str(msg.get("message_id")),
                source="telegram",
                raw=raw,
            )

    text = _pick_text(body.get("text"), body.get("content"), body.get("Content"), body.get("message"))
    user_id = _pick_text(body.get("user_id"), body.get("userid"), body.get("FromUserName"), body.get("from_user"))
    target = _pick_text(body.get("target"), body.get("chat_id"), body.get("group_openid"))
    group = body.get("group")
    msg_id = _pick_text(body.get("msg_id"), body.get("message_id"), body.get("MsgId"), body.get("id"))
    username = _pick_text(body.get("username"), body.get("user_name"), body.get("name"), body.get("nickname"))
    chat_id = _pick_text(body.get("chat_id"), body.get("room_id"), body.get("group_openid"))

    if ch == "qqbot":
        event_type = body.get("type") or ""
        author = body.get("author") or {}
        if isinstance(author, dict):
            user_id = _pick_text(author.get("user_openid"), author.get("id"), user_id)
            username = _pick_text(author.get("username"), author.get("nick"), username)
        if event_type == "GROUP_AT_MESSAGE_CREATE" or body.get("group_openid"):
            group = True
            target = _pick_text(body.get("group_openid"), target)
            chat_id = target
        else:
            group = False if group is None else group
            target = target or user_id
    elif ch in {"wechatbot", "weichatbot"}:
        user_id = user_id or _pick_text(body.get("from"), body.get("sender"))
        target = target or _pick_text(body.get("to"), body.get("room_id"), user_id)
        chat_id = chat_id or target
    elif ch in {"wecom", "wechat", "wework"}:
        target = target or user_id
        chat_id = chat_id or target

    return IncomingMessage(
        channel=ch,
        text=text,
        user_id=user_id,
        username=username,
        target=target,
        group=group,
        msg_id=msg_id,
        chat_id=chat_id,
        source=ch,
        raw=raw,
    )


_wecom_token_cache: dict[str, Any] = {"key": "", "token": "", "expires_at": 0.0}
_qq_token_cache: dict[str, Any] = {"app_id": "", "token": "", "expires_at": 0.0}


def _preview(text: str, limit: int = 500) -> str:
    text = _plain_text(text or "").strip()
    return text[:limit]


def log_notify_event(
    *,
    channel: str,
    direction: str,
    text: str = "",
    user_id: str = "",
    target: str = "",
    status: str = "ok",
    message: str = "",
    event: str | None = None,
    raw: Any = None,
    db: Session | None = None,
) -> None:
    """Best-effort notification event log for status panels and debugging."""
    owns_db = db is None
    session = db or SessionLocal()
    try:
        raw_json = None
        if raw is not None:
            try:
                raw_json = json.dumps(raw, ensure_ascii=False, default=str)[:4000]
            except Exception:
                raw_json = str(raw)[:4000]
        session.add(NotifyEvent(
            channel=(channel or "unknown")[:50],
            direction=(direction or "system")[:20],
            event=(event or "")[:100] or None,
            user_id=(user_id or "")[:255] or None,
            target=(target or "")[:255] or None,
            status=(status or "ok")[:50],
            message=(message or "")[:500] or None,
            text_preview=_preview(text),
            raw_json=raw_json,
        ))
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        logger.debug("log notify event failed: %s", exc)
    finally:
        if owns_db:
            session.close()


def _plain_text(text: str) -> str:
    return (text or "").replace("<b>", "").replace("</b>", "").replace("<br>", "\n")


def _event_enabled(channel_cfg: Any, event: str) -> bool:
    return bool(getattr(channel_cfg, "enabled", False) and getattr(channel_cfg, event, True))


def _send_telegram(text: str, target: str | None = None, reply_markup: dict[str, Any] | None = None) -> SendResult:
    tg = cfg_module.config.notify.telegram
    chat_id = target or tg.chat_id
    if not tg.enabled or not tg.bot_token or not chat_id:
        return SendResult("telegram", False, "telegram not configured")
    try:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(
            f"https://api.telegram.org/bot{tg.bot_token}/sendMessage",
            json=payload,
            timeout=10,
        )
        data = resp.json() if resp.content else {}
        ok = resp.status_code == 200 and data.get("ok")
        return SendResult("telegram", bool(ok), data.get("description") or resp.text[:200], data)
    except Exception as e:
        logger.error("Telegram send error: %s", e)
        return SendResult("telegram", False, str(e))


def _wecom_token() -> str:
    wc = cfg_module.config.notify.wecom
    key = f"{wc.corp_id}:{wc.app_secret}"
    now = time.time()
    if _wecom_token_cache.get("key") == key and _wecom_token_cache.get("token") and now < float(_wecom_token_cache.get("expires_at") or 0):
        return str(_wecom_token_cache["token"])
    base = (wc.proxy or "https://qyapi.weixin.qq.com").rstrip("/")
    resp = requests.get(f"{base}/cgi-bin/gettoken", params={"corpid": wc.corp_id, "corpsecret": wc.app_secret}, timeout=10)
    data = resp.json()
    if data.get("errcode") != 0 or not data.get("access_token"):
        raise RuntimeError(data.get("errmsg") or resp.text[:200])
    _wecom_token_cache.update({"key": key, "token": data["access_token"], "expires_at": now + int(data.get("expires_in") or 7200) - 300})
    return str(data["access_token"])


def _send_wecom(text: str, userid: str | None = None) -> SendResult:
    wc = cfg_module.config.notify.wecom
    if not wc.enabled or not wc.corp_id or not wc.app_secret or not wc.agent_id:
        return SendResult("wecom", False, "wecom not configured")
    try:
        token = _wecom_token()
        base = (wc.proxy or "https://qyapi.weixin.qq.com").rstrip("/")
        content = _plain_text(text)
        # WeCom text messages are byte-limited; split conservatively.
        chunks = []
        buf = ""
        for line in content.splitlines() or [content]:
            candidate = f"{buf}\n{line}" if buf else line
            if len(candidate.encode("utf-8")) > 1800 and buf:
                chunks.append(buf)
                buf = line
            else:
                buf = candidate
        if buf:
            chunks.append(buf)
        last = None
        for chunk in chunks:
            resp = requests.post(
                f"{base}/cgi-bin/message/send",
                params={"access_token": token},
                json={"touser": userid or wc.to_user or "@all", "msgtype": "text", "agentid": int(wc.agent_id), "text": {"content": chunk}, "safe": 0},
                timeout=10,
            )
            last = resp.json() if resp.content else {}
            if last.get("errcode") != 0:
                return SendResult("wecom", False, last.get("errmsg") or resp.text[:200], last)
        return SendResult("wecom", True, "ok", last)
    except Exception as e:
        logger.error("WeCom send error: %s", e)
        return SendResult("wecom", False, str(e))


def _qq_token() -> str:
    qq = cfg_module.config.notify.qqbot
    now_ms = int(time.time() * 1000)
    if _qq_token_cache.get("app_id") == qq.app_id and _qq_token_cache.get("token") and now_ms < int(_qq_token_cache.get("expires_at") or 0):
        return str(_qq_token_cache["token"])
    resp = requests.post("https://bots.qq.com/app/getAppAccessToken", json={"appId": qq.app_id, "clientSecret": qq.app_secret}, timeout=15)
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(data.get("message") or resp.text[:200])
    expires_in = int(data.get("expires_in") or 7200)
    _qq_token_cache.update({"app_id": qq.app_id, "token": token, "expires_at": now_ms + expires_in * 1000 - 300000})
    return str(token)


def _send_qqbot(text: str, target: str | None = None, group: bool | None = None, msg_id: str | None = None) -> SendResult:
    qq = cfg_module.config.notify.qqbot
    if not qq.enabled or not qq.app_id or not qq.app_secret:
        return SendResult("qqbot", False, "qqbot not configured")
    try:
        token = _qq_token()
        is_group = bool(group) if group is not None else bool(qq.group_openid and not target)
        target_id = target or (qq.group_openid if is_group else qq.user_openid)
        if not target_id:
            return SendResult("qqbot", False, "qqbot target missing")
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
            return SendResult("qqbot", False, data.get("message") or resp.text[:200], data)
        return SendResult("qqbot", True, "ok", data)
    except Exception as e:
        logger.error("QQBot send error: %s", e)
        return SendResult("qqbot", False, str(e))


def _send_wechatbot(text: str, target: str | None = None) -> SendResult:
    wb = cfg_module.config.notify.wechatbot
    if not wb.enabled:
        return SendResult("wechatbot", False, "wechatbot not enabled")
    if wb.enable_claw:
        try:
            from app.services.wechatclaw import send_text, load_state
            target_id = target or wb.claw_default_target or ""
            if not target_id:
                targets = load_state().get("known_targets") or {}
                if targets:
                    target_id = sorted(targets.values(), key=lambda x: x.get("last_active") or 0, reverse=True)[0].get("userid") or ""
            if not target_id:
                return SendResult("wechatbot", False, "wechat claw target missing")
            ok = send_text(target_id, _plain_text(text))
            return SendResult("wechatbot", ok, "ok" if ok else "wechat claw send failed")
        except Exception as e:
            logger.error("WeChat Claw send error: %s", e)
            return SendResult("wechatbot", False, str(e))
    if not wb.webhook_url:
        return SendResult("wechatbot", False, "wechatbot webhook_url not configured")
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
        return SendResult("wechatbot", ok, "ok" if ok else str(data)[:200], data)
    except Exception as e:
        logger.error("WeChatBot send error: %s", e)
        return SendResult("wechatbot", False, str(e))


def send_channel(channel: str, text: str, *, target: str | None = None, group: bool | None = None, msg_id: str | None = None, reply_markup: dict[str, Any] | None = None) -> SendResult:
    channel = (channel or "").lower()
    if channel == "telegram":
        result = _send_telegram(text, target=target, reply_markup=reply_markup)
    elif channel in {"wecom", "wechat", "wework"}:
        result = _send_wecom(text, userid=target)
    elif channel == "qqbot":
        result = _send_qqbot(text, target=target, group=group, msg_id=msg_id)
    elif channel in {"wechatbot", "weichatbot"}:
        result = _send_wechatbot(text, target=target)
    else:
        result = SendResult(channel, False, "unknown channel")
    log_notify_event(channel=channel or result.channel, direction="outbound", text=text, target=target or "", status="ok" if result.ok else "error", message=result.message, raw=result.response)
    return result


def send_all(event: str, text: str, *, actions: list[NotifyAction] | None = None) -> list[SendResult]:
    cfg = cfg_module.config.notify
    results: list[SendResult] = []
    tg_markup = telegram_inline_keyboard(actions)
    for name in ("telegram", "wecom", "qqbot", "wechatbot"):
        ch_cfg = getattr(cfg, name)
        if _event_enabled(ch_cfg, event):
            results.append(send_channel(name, text, reply_markup=tg_markup if name == "telegram" else None))
    return results


def _assistant_channel_key(channel: str, user_id: str = "", target: str = "") -> str:
    identity = (user_id or target or "anonymous").strip() or "anonymous"
    safe = "".join(ch if ch.isalnum() or ch in "-_:." else "_" for ch in f"{channel}:{identity}")
    return f"notify:{safe}"[:240]


def _get_or_create_notify_conversation(db: Session, channel: str, user_id: str = "", target: str = "") -> AssistantConversation:
    title = _assistant_channel_key(channel, user_id, target)
    conv = db.query(AssistantConversation).filter(AssistantConversation.title == title).order_by(AssistantConversation.updated_at.desc()).first()
    if conv:
        return conv
    conv = AssistantConversation(title=title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _latest_pending_action(db: Session, conversation_id: int) -> AssistantAction | None:
    return (
        db.query(AssistantAction)
        .filter(AssistantAction.conversation_id == conversation_id, AssistantAction.status == "pending")
        .order_by(AssistantAction.created_at.desc())
        .first()
    )


def _looks_confirm(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {"确认", "确认执行", "执行", "同意", "可以", "是", "yes", "y", "ok", "confirm"}


def _looks_cancel(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {"取消", "不要", "停止", "算了", "否", "no", "n", "cancel"}


def handle_incoming_message(db: Session, incoming: IncomingMessage) -> dict[str, Any]:
    """Forward a normalized inbound chat message to Music Sub Assistant and reply on the same channel.

    Unlike the web UI, messaging surfaces need sticky sessions and a simple
    confirm/cancel grammar so high-risk assistant actions can be completed from
    WeCom/QQ/WeChat/Telegram without opening the browser.
    """
    from app.services.assistant.service import AssistantService

    channel = (incoming.channel or "").lower()
    text = (incoming.text or "").strip()
    user_id = incoming.user_id or incoming.target or ""
    target = incoming.target or incoming.chat_id or user_id
    group = incoming.group
    msg_id = incoming.msg_id or None
    log_notify_event(channel=channel, direction="inbound", text=text, user_id=user_id, target=target, status="ok" if text else "ignored", message="inbound message", raw={"incoming": incoming.meta(), "raw": incoming.raw}, db=db)
    if not text:
        return {"ok": False, "message": "empty text"}
    ch_cfg = getattr(cfg_module.config.notify, "wechatbot" if channel in {"wechatbot", "weichatbot"} else channel, None)
    if not ch_cfg or not getattr(ch_cfg, "assistant_chat", True):
        return {"ok": False, "message": "assistant chat disabled for channel"}

    service = AssistantService(db)
    conv = _get_or_create_notify_conversation(db, channel, user_id, target)
    pending = _latest_pending_action(db, conv.id)
    reply_markup = None

    if pending and _looks_cancel(text):
        res = service.cancel_action(pending.action_id)
        reply = res.get("message") or "已取消。"
    elif pending and _looks_confirm(text):
        res = service.confirm_action(pending.action_id)
        reply = res.get("message") or ("已执行。" if res.get("ok") else "执行失败。")
    else:
        res = service.chat(text, conv.id)
        reply = res.get("message") or "助手没有返回内容。"
        if res.get("needs_confirm") and res.get("action_id"):
            if channel == "telegram":
                reply += "\n\n点击按钮确认，或直接回复“确认”/“取消”。"
                reply_markup = {"inline_keyboard": [[
                    {"text": "✅ 确认执行", "callback_data": "ms_confirm"},
                    {"text": "❌ 取消", "callback_data": "ms_cancel"},
                ]]}
            else:
                reply += "\n\n回复“确认”执行，或回复“取消”放弃。"

    # Prefer explicit target; otherwise reply to inbound user id.
    send_res = send_channel(channel, reply, target=target or user_id or None, group=group, msg_id=msg_id, reply_markup=reply_markup)
    return {"ok": bool(res.get("ok", True)), "conversation_id": conv.id, "incoming": incoming.meta(), "assistant": res, "send": send_res.__dict__}


def handle_incoming_assistant(db: Session, *, channel: str, text: str, user_id: str = "", target: str = "", group: bool | None = None, msg_id: str | None = None) -> dict[str, Any]:
    """Backward-compatible wrapper for older call sites."""
    return handle_incoming_message(db, IncomingMessage(channel=channel, text=text, user_id=user_id, target=target, group=group, msg_id=msg_id))


# Event helpers ----------------------------------------------------------------
def notify_download_added(torrent_name: str, site: str):
    send_all("on_download_added", f"⬇️ <b>开始下载</b>\n{torrent_name}\n来源: {site}")


def notify_download_complete(torrent_name: str, file_count: int):
    send_all("on_download_complete", f"✅ <b>下载完成</b>\n{torrent_name}\n文件数: {file_count}")


def notify_scrape_complete(torrent_name: str, scraped: int, total: int):
    send_all("on_scrape_complete", f"🎵 <b>刮削完成</b>\n{torrent_name}\n成功: {scraped}/{total}")


def notify_error(context: str, error: str):
    send_all("on_error", f"❌ <b>错误</b>\n{context}\n{error[:200]}")


def notify_cleanup_candidates(candidate_count: int, qb_and_db_count: int, db_only_count: int, total_size: float, total_amount_left: float):
    size_mb = total_size / 1024 / 1024 if total_size else 0
    left_mb = total_amount_left / 1024 / 1024 if total_amount_left else 0
    send_all(
        "on_cleanup_candidates",
        "🧹 <b>Music Sub 清理扫描发现候选</b>\n"
        f"候选任务: {candidate_count}\n"
        f"qB+DB: {qb_and_db_count} · 仅DB: {db_only_count}\n"
        f"影响大小: {size_mb:.1f} MB · 剩余未下载: {left_mb:.1f} MB\n"
        "请到任务列表执行清理扫描确认。",
    )
