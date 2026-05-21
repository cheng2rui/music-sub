"""Multi-channel notification service.

This module keeps Music Sub's notification layer intentionally small: one unified
outbound API and one normalized
inbound path that can forward user messages to the built-in assistant.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

import app.config as cfg_module
from app.db import SessionLocal
from app.models import AssistantAction, AssistantConversation, NotifyEvent
from app.services.notify_channels import qqbot as qqbot_channel
from app.services.notify_channels import telegram as telegram_channel
from app.services.notify_channels import wechatbot as wechatbot_channel
from app.services.notify_channels import wecom as wecom_channel

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
    command: str = ""
    path: str = ""
    style: str = "default"


def _public_url(path: str) -> str:
    base = (cfg_module.config.notify.public_base_url or "").strip().rstrip("/")
    if not base or not path:
        return ""
    if not base.startswith(("https://", "http://")):
        return ""
    return base + (path if path.startswith("/") else f"/{path}")


def telegram_inline_keyboard(actions: list[NotifyAction] | None) -> dict[str, Any] | None:
    if not actions:
        return None
    row = []
    for action in actions[:6]:
        label = (action.label or action.command or "Action")[:64]
        url = _public_url(action.path)
        if url:
            row.append({"text": label, "url": url})
            continue
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

    Provider
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


DEFAULT_NOTIFY_TEMPLATES: dict[str, str] = {
    "download_added": "⬇️ <b>开始下载</b>\n{name}\n来源: {site}",
    "download_complete": "✅ <b>下载完成</b>\n{name}\n文件数: {file_count}",
    "download_complete_batch": "✅ <b>下载完成 · {album_count} 张专辑 / {track_count} 首</b>\n\n{album_sections}\n\n总大小：{total_size_mb:.1f} MB",
    "scrape_complete": "🎵 <b>刮削完成</b>\n{name}\n成功: {scraped}/{total}",
    "scrape_complete_batch": "🎵 <b>刮削完成 · {album_count} 张专辑 / {scraped}/{total} 首</b>\n\n{album_sections}\n\n总大小：{total_size_mb:.1f} MB",
    "error": "❌ <b>错误</b>\n{context}\n{error}",
    "cleanup_candidates": "🧹 <b>Music Sub 清理扫描发现候选</b>\n候选任务: {candidate_count}\nqB+DB: {qb_and_db_count} · 仅DB: {db_only_count}\n影响大小: {total_size_mb:.1f} MB · 剩余未下载: {total_amount_left_mb:.1f} MB\n请到任务列表执行清理扫描确认。",
}


class _SafeTemplateDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_template_text(template: str, context: dict[str, Any]) -> str:
    """Render one template string with safe `{variable}` substitution."""
    return (template or "").format_map(_SafeTemplateDict(**(context or {})))


def render_notify_template(event: str, **context: Any) -> str:
    """Render a notification template with safe `{variable}` substitution."""
    template = (cfg_module.config.notify.templates or {}).get(event) or DEFAULT_NOTIFY_TEMPLATES.get(event) or "{message}"
    try:
        return render_template_text(template, context)
    except Exception as exc:
        logger.warning("render notify template failed for %s: %s", event, exc)
        fallback = DEFAULT_NOTIFY_TEMPLATES.get(event) or "{message}"
        return render_template_text(fallback, context)


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


def _send_telegram_chat_action(target: str | None = None, action: str = "typing") -> None:
    telegram_channel.send_chat_action(target=target, action=action)


def _start_telegram_typing(target: str | None = None, *, interval: float = 4.5, max_seconds: int = 300) -> Callable[[], None]:
    return telegram_channel.start_typing(target=target, interval=interval, max_seconds=max_seconds)


def _send_telegram(text: str, target: str | None = None, reply_markup: dict[str, Any] | None = None, image_path: str | None = None) -> SendResult:
    if image_path and os.path.exists(image_path):
        result = telegram_channel.send_photo(image_path, caption=text, target=target, reply_markup=reply_markup)
    else:
        result = telegram_channel.send_message(text, target=target, reply_markup=reply_markup)
    return SendResult(result.channel, result.ok, result.message, result.response)


def _send_wecom(text: str, userid: str | None = None) -> SendResult:
    result = wecom_channel.send_text(text, userid=userid)
    return SendResult(result.channel, result.ok, result.message, result.response)


def _send_qqbot(text: str, target: str | None = None, group: bool | None = None, msg_id: str | None = None) -> SendResult:
    result = qqbot_channel.send_text(text, target=target, group=group, msg_id=msg_id)
    return SendResult(result.channel, result.ok, result.message, result.response)


def _send_wechatbot(text: str, target: str | None = None) -> SendResult:
    result = wechatbot_channel.send_text(text, target=target)
    return SendResult(result.channel, result.ok, result.message, result.response)


def send_channel(channel: str, text: str, *, target: str | None = None, group: bool | None = None, msg_id: str | None = None, reply_markup: dict[str, Any] | None = None, image_path: str | None = None) -> SendResult:
    channel = (channel or "").lower()
    if channel == "telegram":
        result = _send_telegram(text, target=target, reply_markup=reply_markup, image_path=image_path)
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


def send_all(event: str, text: str, *, actions: list[NotifyAction] | None = None, image_path: str | None = None) -> list[SendResult]:
    cfg = cfg_module.config.notify
    results: list[SendResult] = []
    tg_markup = telegram_inline_keyboard(actions)
    for name in ("telegram", "wecom", "qqbot", "wechatbot"):
        ch_cfg = getattr(cfg, name)
        if _event_enabled(ch_cfg, event):
            results.append(send_channel(name, text, reply_markup=tg_markup if name == "telegram" else None, image_path=image_path if name == "telegram" else None))
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


def _strip_ai_prefix(text: str) -> tuple[str, bool]:
    stripped = (text or "").strip()
    lower = stripped.lower()
    if lower == "/ai":
        return "", True
    if lower.startswith("/ai ") or lower.startswith("/ai\n"):
        return stripped[3:].strip(), True
    return stripped, False


def _is_shortcut_text(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {
        "查看任务", "任务", "打开任务", "下载任务", "任务状态",
        "打开音乐库", "音乐库", "查看音乐库", "曲库", "曲库状态", "音乐库状态",
        "帮我看看曲库状态", "看看曲库状态",
        "打开治理", "治理", "音乐库治理", "曲库治理",
        "清理扫描", "执行清理扫描",
    }


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
    text, explicit_ai = _strip_ai_prefix(text)
    if explicit_ai and not text:
        return {"ok": False, "message": "empty /ai message"}
    ch_cfg = getattr(cfg_module.config.notify, "wechatbot" if channel in {"wechatbot", "weichatbot"} else channel, None)
    if not ch_cfg or not getattr(ch_cfg, "assistant_chat", True):
        return {"ok": False, "message": "assistant chat disabled for channel"}

    service = AssistantService(db)
    conv = _get_or_create_notify_conversation(db, channel, user_id, target)
    pending = _latest_pending_action(db, conv.id)
    reply_markup = None
    assistant_cfg = cfg_module.config.assistant
    if (
        not pending
        and not explicit_ai
        and not getattr(assistant_cfg, "global_chat", True)
        and not _is_shortcut_text(text)
    ):
        # Non-global mode: ordinary chat is ignored unless the
        # user explicitly invokes /ai.  Do not send noisy fallback messages.
        return {"ok": True, "conversation_id": conv.id, "message": "ignored: /ai required", "ignored": True}

    stop_typing = _start_telegram_typing(target=target or user_id or None) if channel == "telegram" else None
    try:
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
    finally:
        if stop_typing:
            stop_typing()


def handle_incoming_assistant(db: Session, *, channel: str, text: str, user_id: str = "", target: str = "", group: bool | None = None, msg_id: str | None = None) -> dict[str, Any]:
    """Backward-compatible wrapper for older call sites."""
    return handle_incoming_message(db, IncomingMessage(channel=channel, text=text, user_id=user_id, target=target, group=group, msg_id=msg_id))


# Event helpers ----------------------------------------------------------------
def notify_download_added(torrent_name: str, site: str):
    text = render_notify_template("download_added", name=torrent_name, site=site)
    log_notify_event(channel="system", direction="internal", event="download_added", text=text, status="ok", message=f"{site} download added")
    send_all("on_download_added", text)


_download_batch_lock = threading.Lock()
_download_batch_timer: threading.Timer | None = None
_download_batch_items: list[dict[str, Any]] = []


def _format_size_mb(size_bytes: int | float | None) -> float:
    return round(float(size_bytes or 0) / 1024 / 1024, 1)


def _guess_cover_path(album_dir: str | None) -> str:
    if not album_dir:
        return ""
    base = Path(album_dir)
    for name in ("cover.jpg", "cover.png", "folder.jpg", "front.jpg", "Cover.jpg"):
        p = base / name
        if p.exists():
            return str(p)
    return ""


def _download_track_payload(file_path: str) -> dict[str, Any]:
    p = Path(file_path)
    return {
        "title": p.stem,
        "format": p.suffix.lstrip(".").upper() or "AUDIO",
        "size_bytes": p.stat().st_size if p.exists() else 0,
        "album_dir": str(p.parent),
    }


def _flush_download_complete_batch() -> None:
    global _download_batch_timer, _download_batch_items
    with _download_batch_lock:
        items = _download_batch_items
        _download_batch_items = []
        _download_batch_timer = None
    if not items:
        return

    albums: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        album_key = item.get("name") or Path(item.get("album_dir") or "").name or "下载完成"
        albums.setdefault(album_key, []).append(item)

    sections: list[str] = []
    total_size = 0
    first_cover = ""
    for album, tracks in albums.items():
        if not first_cover:
            first_cover = _guess_cover_path(tracks[0].get("album_dir"))
        album_size = sum(int(t.get("size_bytes") or 0) for t in tracks)
        total_size += album_size
        sections.append(f"<b>💿 {album}</b> · {len(tracks)} 首 · {_format_size_mb(album_size):.1f} MB")
        for idx, track in enumerate(tracks[:12], 1):
            sections.append(f"{idx}. {track.get('title') or '-'} · {track.get('format') or '-'} · {_format_size_mb(track.get('size_bytes')):.1f} MB")
        if len(tracks) > 12:
            sections.append(f"… 还有 {len(tracks) - 12} 首")
        sections.append("")

    text = render_notify_template(
        "download_complete_batch",
        album_count=len(albums),
        track_count=len(items),
        album_sections="\n".join(sections).strip(),
        total_size_mb=_format_size_mb(total_size),
    )
    log_notify_event(channel="system", direction="internal", event="download_complete", text=text, status="ok", message=f"{len(items)} tracks batched", raw={"items": items[:50], "image_path": first_cover})
    send_all(
        "on_download_complete",
        text,
        image_path=first_cover,
        actions=[
            NotifyAction("📚 打开音乐库", "打开音乐库", "/library"),
            NotifyAction("⬇️ 查看任务", "查看任务", "/tasks"),
        ],
    )


def notify_download_complete(torrent_name: str, file_count: int, files: list[str] | None = None):
    delay = max(0, min(int(getattr(cfg_module.config.notify, "download_complete_batch_delay_seconds", 20) or 0), 3600))
    tracks = [_download_track_payload(path) for path in (files or [])]
    if not tracks:
        tracks = [{"title": torrent_name, "format": "-", "size_bytes": 0, "album_dir": ""} for _ in range(max(1, int(file_count or 1)))]
    for track in tracks:
        track["name"] = torrent_name
    if delay <= 0:
        with _download_batch_lock:
            _download_batch_items.extend(tracks)
        _flush_download_complete_batch()
        return
    global _download_batch_timer
    with _download_batch_lock:
        _download_batch_items.extend(tracks)
        if _download_batch_timer:
            _download_batch_timer.cancel()
        _download_batch_timer = threading.Timer(delay, _flush_download_complete_batch)
        _download_batch_timer.daemon = True
        _download_batch_timer.start()
    text = f"下载完成已加入聚合通知：{torrent_name}（{len(tracks)} 首，约 {delay}s 后推送）"
    log_notify_event(channel="system", direction="internal", event="download_complete_pending", text=text, status="ok", message=f"delay {delay}s")


_scrape_batch_lock = threading.Lock()
_scrape_batch_timer: threading.Timer | None = None
_scrape_batch_items: list[dict[str, Any]] = []


def _flush_scrape_complete_batch() -> None:
    global _scrape_batch_timer, _scrape_batch_items
    with _scrape_batch_lock:
        items = _scrape_batch_items
        _scrape_batch_items = []
        _scrape_batch_timer = None
    if not items:
        return

    albums: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        album_key = item.get("name") or Path(item.get("album_dir") or "").name or "刮削完成"
        albums.setdefault(album_key, []).append(item)
    total_expected = sum(max([int(t.get("total_hint") or 1) for t in tracks] or [len(tracks)]) for tracks in albums.values())

    sections: list[str] = []
    total_size = 0
    first_cover = ""
    for album, tracks in albums.items():
        if not first_cover:
            first_cover = _guess_cover_path(tracks[0].get("album_dir"))
        album_size = sum(int(t.get("size_bytes") or 0) for t in tracks)
        total_size += album_size
        sections.append(f"<b>💿 {album}</b> · {len(tracks)} 首 · {_format_size_mb(album_size):.1f} MB")
        for idx, track in enumerate(tracks[:12], 1):
            sections.append(f"{idx}. {track.get('title') or '-'} · {track.get('format') or '-'} · {_format_size_mb(track.get('size_bytes')):.1f} MB")
        if len(tracks) > 12:
            sections.append(f"… 还有 {len(tracks) - 12} 首")
        sections.append("")

    scraped = len(items)
    total = max(scraped, total_expected)
    text = render_notify_template(
        "scrape_complete_batch",
        album_count=len(albums),
        scraped=scraped,
        total=total,
        track_count=scraped,
        album_sections="\n".join(sections).strip(),
        total_size_mb=_format_size_mb(total_size),
    )
    log_notify_event(channel="system", direction="internal", event="scrape_complete", text=text, status="ok", message=f"{scraped}/{total} tracks batched", raw={"items": items[:50], "image_path": first_cover})
    send_all(
        "on_scrape_complete",
        text,
        image_path=first_cover,
        actions=[
            NotifyAction("📚 打开音乐库", "打开音乐库", "/library"),
            NotifyAction("🛠️ 治理", "打开治理", "/library?health=1"),
        ],
    )


def notify_scrape_complete(torrent_name: str, scraped: int, total: int, files: list[str] | None = None):
    delay = max(0, min(int(getattr(cfg_module.config.notify, "scrape_complete_batch_delay_seconds", 20) or 0), 3600))
    tracks = [_download_track_payload(path) for path in (files or [])]
    if not tracks:
        tracks = [{"title": torrent_name, "format": "-", "size_bytes": 0, "album_dir": ""} for _ in range(max(1, int(scraped or total or 1)))]
    for track in tracks:
        track["name"] = torrent_name
        track["total_hint"] = total
    if delay <= 0:
        with _scrape_batch_lock:
            _scrape_batch_items.extend(tracks)
        _flush_scrape_complete_batch()
        return
    global _scrape_batch_timer
    with _scrape_batch_lock:
        _scrape_batch_items.extend(tracks)
        if _scrape_batch_timer:
            _scrape_batch_timer.cancel()
        _scrape_batch_timer = threading.Timer(delay, _flush_scrape_complete_batch)
        _scrape_batch_timer.daemon = True
        _scrape_batch_timer.start()
    text = f"刮削完成已加入聚合通知：{torrent_name}（{scraped}/{total}，约 {delay}s 后推送）"
    log_notify_event(channel="system", direction="internal", event="scrape_complete_pending", text=text, status="ok", message=f"delay {delay}s")


def notify_error(context: str, error: str):
    text = render_notify_template("error", context=context, error=(error or "")[:200])
    log_notify_event(channel="system", direction="internal", event="error", text=text, status="error", message=context)
    send_all("on_error", text)


def notify_cleanup_candidates(candidate_count: int, qb_and_db_count: int, db_only_count: int, total_size: float, total_amount_left: float):
    size_mb = total_size / 1024 / 1024 if total_size else 0
    left_mb = total_amount_left / 1024 / 1024 if total_amount_left else 0
    text = render_notify_template(
        "cleanup_candidates",
            candidate_count=candidate_count,
            qb_and_db_count=qb_and_db_count,
            db_only_count=db_only_count,
            total_size=total_size,
            total_amount_left=total_amount_left,
            total_size_mb=size_mb,
            total_amount_left_mb=left_mb,
        )
    log_notify_event(channel="system", direction="internal", event="cleanup_candidates", text=text, status="ok", message=f"{candidate_count} candidates")
    send_all(
        "on_cleanup_candidates",
        text,
        actions=[
            NotifyAction("⬇️ 查看任务", "查看任务", "/tasks"),
            NotifyAction("🧹 清理扫描", "清理扫描", "/tasks?cleanup=1"),
        ],
    )
