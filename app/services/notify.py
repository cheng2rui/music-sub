"""Multi-channel notification service.

Inspired by MoviePilot's message modules, this module keeps Music Sub's first
implementation intentionally small: one unified outbound API and one normalized
inbound path that can forward user messages to the built-in assistant.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests
from sqlalchemy.orm import Session

import app.config as cfg_module
from app.models import AssistantAction, AssistantConversation

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    channel: str
    ok: bool
    message: str = ""
    response: Any = None


_wecom_token_cache: dict[str, Any] = {"key": "", "token": "", "expires_at": 0.0}
_qq_token_cache: dict[str, Any] = {"app_id": "", "token": "", "expires_at": 0.0}


def _plain_text(text: str) -> str:
    return (text or "").replace("<b>", "").replace("</b>", "").replace("<br>", "\n")


def _event_enabled(channel_cfg: Any, event: str) -> bool:
    return bool(getattr(channel_cfg, "enabled", False) and getattr(channel_cfg, event, True))


def _send_telegram(text: str) -> SendResult:
    tg = cfg_module.config.notify.telegram
    if not tg.enabled or not tg.bot_token or not tg.chat_id:
        return SendResult("telegram", False, "telegram not configured")
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{tg.bot_token}/sendMessage",
            json={"chat_id": tg.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
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
    if not wb.enabled or not wb.webhook_url:
        return SendResult("wechatbot", False, "wechatbot not configured")
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


def send_channel(channel: str, text: str, *, target: str | None = None, group: bool | None = None, msg_id: str | None = None) -> SendResult:
    channel = (channel or "").lower()
    if channel == "telegram":
        return _send_telegram(text)
    if channel in {"wecom", "wechat", "wework"}:
        return _send_wecom(text, userid=target)
    if channel == "qqbot":
        return _send_qqbot(text, target=target, group=group, msg_id=msg_id)
    if channel in {"wechatbot", "weichatbot"}:
        return _send_wechatbot(text, target=target)
    return SendResult(channel, False, "unknown channel")


def send_all(event: str, text: str) -> list[SendResult]:
    cfg = cfg_module.config.notify
    results: list[SendResult] = []
    for name in ("telegram", "wecom", "qqbot", "wechatbot"):
        ch_cfg = getattr(cfg, name)
        if _event_enabled(ch_cfg, event):
            results.append(send_channel(name, text))
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


def handle_incoming_assistant(db: Session, *, channel: str, text: str, user_id: str = "", target: str = "", group: bool | None = None, msg_id: str | None = None) -> dict[str, Any]:
    """Forward a normalized inbound chat message to Music Sub Assistant and reply on the same channel.

    Unlike the web UI, messaging surfaces need sticky sessions and a simple
    confirm/cancel grammar so high-risk assistant actions can be completed from
    WeCom/QQ/WeChat without opening the browser.
    """
    from app.services.assistant.service import AssistantService

    text = (text or "").strip()
    if not text:
        return {"ok": False, "message": "empty text"}
    ch_cfg = getattr(cfg_module.config.notify, "wechatbot" if channel in {"wechatbot", "weichatbot"} else channel, None)
    if not ch_cfg or not getattr(ch_cfg, "assistant_chat", True):
        return {"ok": False, "message": "assistant chat disabled for channel"}

    service = AssistantService(db)
    conv = _get_or_create_notify_conversation(db, channel, user_id, target)
    pending = _latest_pending_action(db, conv.id)

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
            reply += "\n\n回复“确认”执行，或回复“取消”放弃。"

    # Prefer explicit target; otherwise reply to inbound user id.
    send_res = send_channel(channel, reply, target=target or user_id or None, group=group, msg_id=msg_id)
    return {"ok": bool(res.get("ok", True)), "conversation_id": conv.id, "assistant": res, "send": send_res.__dict__}


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
