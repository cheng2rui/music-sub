"""Assistant orchestration service."""
from __future__ import annotations

import concurrent.futures
import datetime
import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app import config as cfg_module
from app.models import AssistantAction, AssistantConversation, AssistantMessage, MusicFile
from app.services.assistant.llm import AssistantLLMClient, AssistantLLMError, _sanitize_error
from app.services.assistant.prompts import SYSTEM_PROMPT
from app.services.assistant.tools import execute_tool, openai_tools, tool_catalog, tool_risk

logger = logging.getLogger(__name__)


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _safe_json_loads(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _truncate_text(text: str, limit: int = 8000) -> str:
    if len(text or "") <= limit:
        return text or ""
    return (text or "")[:limit] + "...（已截断）"


def _tool_signature(name: str, args: dict[str, Any]) -> str:
    """Stable signature for lightweight loop detection."""
    return f"{name}:{json.dumps(args or {}, ensure_ascii=False, sort_keys=True, default=str)}"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 3)


def _looks_like_tool_leak(text: str) -> bool:
    markers = ["[工具结果", "</minimax:tool_call>", "<minimax:tool_call", "</think>", "<tool_use", "tool_call_id"]
    return any(m in (text or "") for m in markers)


def _clean_assistant_output(text: str) -> str:
    """Remove model/tool protocol leakage before persisting or sending to users."""
    text = text or ""
    # Strip common thinking/tool protocol tags.  Some Anthropic-compatible
    # providers (notably MiniMax) may return fallback XML-ish tool text when
    # tool parsing fails; never expose that raw protocol to Telegram/Web UI.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"</?think>", "", text, flags=re.I)
    text = re.sub(r"<minimax:tool_call[^>]*>.*?</minimax:tool_call>", "", text, flags=re.S | re.I)
    text = re.sub(r"</?minimax:tool_call[^>]*>", "", text, flags=re.I)
    text = re.sub(r"\[工具结果\s+[^\]]+\]\s*\{.*?(?=\n\s*(?:\[工具结果|$))", "", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _norm_album_name(value: str | None) -> str:
    return re.sub(r"[\s\-_.·:：,，()（）\[\]【】《》]+", "", (value or "").lower())


def _compact_tool_result(tool_name: str, result: Any) -> Any:
    """Keep full tool results in DB, but feed only compact data back to the LLM.

    Tool output should be useful for the next
    decision, not pollute the whole conversation context.
    """
    if not isinstance(result, dict):
        return result
    if tool_name == "search_pt":
        return {
            "queries": result.get("queries") or [],
            "sites": result.get("sites") or [],
            "candidates": (result.get("candidates") or [])[:8],
            "items": (result.get("items") or [])[:8],
            "instruction": result.get("instruction") or "",
        }
    if tool_name == "search_online":
        return {
            "candidates": (result.get("candidates") or [])[:6],
            "items": (result.get("items") or [])[:6],
            "instruction": result.get("instruction") or "",
        }
    if tool_name == "search_download_candidates":
        candidates = (result or {}).get("candidates") or []
        pt_candidates = ((result or {}).get("pt") or {}).get("candidates") or []
        online_candidates = ((result or {}).get("online") or {}).get("candidates") or []
        return {
            "keyword": (result or {}).get("keyword"),
            "candidates": candidates[:8],
            "pt": {"candidates": pt_candidates[:5], "total": len(pt_candidates), "error": ((result or {}).get("pt") or {}).get("error")},
            "online": {"candidates": online_candidates[:5], "total": len(online_candidates), "error": ((result or {}).get("online") or {}).get("error")},
            "instruction": (result or {}).get("instruction") or "",
        }
    if tool_name in {"list_tasks", "list_subscriptions", "search_library"}:
        return {"items": (result.get("items") or [])[:15]}
    if tool_name == "query_library_health":
        if "totals" in result:
            return {"totals": result.get("totals") or {}, "samples": result.get("samples") or {}}
        return {"kind": result.get("kind"), "total": result.get("total"), "items": (result.get("items") or [])[:12]}
    if tool_name == "read_recent_logs":
        return {"level": result.get("level") or "", "total": result.get("total") or 0, "lines": (result.get("lines") or [])[-80:]}
    if tool_name == "rescrape_album":
        return {"ok": result.get("ok"), "job_id": result.get("job_id"), "total": result.get("total"), "message": result.get("message")}
    if tool_name == "organize_task":
        return {"ok": result.get("ok"), "task_id": result.get("task_id"), "status": result.get("status"), "message": result.get("message")}
    if tool_name == "complete_album":
        return {
            "ok": result.get("ok"),
            "dry_run": result.get("dry_run"),
            "existing": result.get("existing"),
            "candidate_count": len(result.get("candidates") or []),
            "candidates": (result.get("candidates") or [])[:10],
            "downloaded": result.get("downloaded") or [],
            "errors": (result.get("errors") or [])[:10],
        }
    return result


class AssistantService:
    def __init__(self, db: Session):
        self.db = db

    def _enabled_tool_names(self) -> set[str]:
        return set(cfg_module.config.assistant.enabled_tools or [])

    def capabilities(self) -> dict[str, Any]:
        cfg = cfg_module.config.assistant
        enabled_tools = self._enabled_tool_names()
        tools = openai_tools(enabled_tools)
        warnings = []
        if not cfg.enabled:
            warnings.append("智能助手未启用")
        if cfg.enabled and not cfg.provider.model:
            warnings.append("未配置模型 ID")
        if cfg.enabled and not cfg.provider.base_url:
            warnings.append("未配置模型服务地址")
        return {
            "enabled": cfg.enabled,
            "provider": cfg.provider.provider,
            "model": cfg.provider.model,
            "tools": [t["function"]["name"] for t in tools],
            "tool_catalog": tool_catalog(enabled_tools),
            "warnings": warnings,
            "risk_control": {
                "download": cfg.require_confirm_for_download,
                "delete": cfg.require_confirm_for_delete,
                "apply_tools": cfg.require_confirm_for_apply_tools,
            },
        }

    def list_conversations(self) -> list[AssistantConversation]:
        return self.db.query(AssistantConversation).order_by(AssistantConversation.updated_at.desc()).limit(50).all()

    def create_conversation(self, title: str = "") -> AssistantConversation:
        conv = AssistantConversation(title=title or "新对话")
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def get_messages(self, conversation_id: int) -> list[AssistantMessage]:
        return self.db.query(AssistantMessage).filter(AssistantMessage.conversation_id == conversation_id).order_by(AssistantMessage.created_at.asc()).all()

    def delete_conversation(self, conversation_id: int) -> dict[str, Any]:
        self.db.query(AssistantMessage).filter(AssistantMessage.conversation_id == conversation_id).delete(synchronize_session=False)
        self.db.query(AssistantAction).filter(AssistantAction.conversation_id == conversation_id).delete(synchronize_session=False)
        conv = self.db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first()
        if conv:
            self.db.delete(conv)
        self.db.commit()
        return {"ok": True}

    def recent_activity(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 200))
        actions = self.db.query(AssistantAction).order_by(AssistantAction.created_at.desc()).limit(limit).all()
        tool_messages = (
            self.db.query(AssistantMessage)
            .filter(AssistantMessage.role == "tool")
            .order_by(AssistantMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        rows: list[dict[str, Any]] = []
        for action in actions:
            args = _safe_json_loads(action.tool_args_json)
            result = _safe_json_loads(action.result_json)
            rows.append({
                "type": "action",
                "id": action.action_id,
                "conversation_id": action.conversation_id,
                "tool_name": action.tool_name,
                "status": action.status,
                "risk": action.risk,
                "summary": self._action_summary(action.tool_name, args, action.risk),
                "args": args,
                "result": _compact_tool_result(action.tool_name, result) if result else {},
                "created_at": action.created_at,
                "updated_at": action.updated_at,
            })
        for msg in tool_messages:
            result = _safe_json_loads(msg.tool_result_json)
            rows.append({
                "type": "tool",
                "id": msg.id,
                "conversation_id": msg.conversation_id,
                "tool_name": msg.tool_name,
                "status": msg.status or "done",
                "risk": tool_risk(msg.tool_name or ""),
                "summary": f"调用工具：{msg.tool_name}",
                "args": _safe_json_loads(msg.tool_args_json),
                "result": _compact_tool_result(msg.tool_name or "", result) if result else {},
                "created_at": msg.created_at,
                "updated_at": msg.created_at,
            })
        rows.sort(key=lambda x: x.get("updated_at") or x.get("created_at") or datetime.datetime.min, reverse=True)
        return rows[:limit]

    def _save_message(self, conversation_id: int, role: str, content: str = "", **kwargs) -> AssistantMessage:
        msg = AssistantMessage(conversation_id=conversation_id, role=role, content=content or "", **kwargs)
        self.db.add(msg)
        conv = self.db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first()
        if conv:
            conv.updated_at = datetime.datetime.utcnow()
            if not conv.title or conv.title == "新对话":
                conv.title = (content or "新对话")[:40]
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def _history_for_llm(self, conversation_id: int) -> list[dict[str, Any]]:
        cfg = cfg_module.config.assistant
        provider_cfg = cfg.provider
        rows = self.get_messages(conversation_id)[-(cfg.max_history_messages or 20):]
        max_tokens = max(4, int(getattr(provider_cfg, "max_context_tokens_k", 64) or 64)) * 1024
        # Rough but practical estimate: CJK/English mixed text averages ~3 chars/token.
        # Reserve room for tool schemas and model output so history does not crowd them out.
        history_budget = max(2048, int(max_tokens * 0.55))
        system_msg = {"role": "system", "content": SYSTEM_PROMPT}
        system_tokens = _estimate_tokens(SYSTEM_PROMPT)
        selected: list[dict[str, Any]] = []
        used = system_tokens

        rendered_rows: list[dict[str, Any]] = []
        for row in rows:
            if row.role == "user":
                rendered_rows.append({"role": row.role, "content": row.content or ""})
            elif row.role == "assistant":
                content = _clean_assistant_output(row.content or "")
                if content and not _looks_like_tool_leak(content):
                    rendered_rows.append({"role": "assistant", "content": content})
            elif row.role == "tool":
                # Persisted tool messages are replayed as plain assistant context instead
                # of protocol-level `tool` messages. OpenAI/Anthropic both require a
                # preceding assistant tool_call/tool_use in the same request; after a
                # page reload or a later user turn we only need the data as context.
                raw_result = _safe_json_loads(row.tool_result_json) if row.tool_result_json else {}
                result = _json_dumps(_compact_tool_result(row.tool_name or "", raw_result)) if raw_result else (row.content or "{}")
                rendered_rows.append({"role": "assistant", "content": f"[工具结果 {row.tool_name or ''}]\n{_truncate_text(result)}"})

        for msg in reversed(rendered_rows):
            cost = _estimate_tokens(msg.get("content") or "")
            if selected and used + cost > history_budget:
                break
            selected.append(msg)
            used += cost
        selected.reverse()
        return [system_msg, *selected]

    def _llm_client(self) -> AssistantLLMClient:
        cfg = cfg_module.config.assistant.provider
        return AssistantLLMClient(
            provider=cfg.provider,
            runtime=cfg.runtime,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            model=cfg.model,
            temperature=cfg.temperature,
            timeout_seconds=cfg.timeout_seconds,
            max_context_tokens_k=getattr(cfg, "max_context_tokens_k", 64),
            thinking_level=getattr(cfg, "thinking_level", "off"),
        )

    def _chat_response(
        self,
        conversation_id: int,
        message: str,
        *,
        ok: bool = True,
        error_code: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        needs_confirm: bool = False,
        action_id: str | None = None,
    ) -> dict[str, Any]:
        message = _clean_assistant_output(message or "") or "助手没有返回可显示内容。"
        data = {
            "ok": ok,
            "conversation_id": conversation_id,
            "message": message,
            "tool_calls": tool_calls or [],
            "needs_confirm": needs_confirm,
        }
        if action_id:
            data["action_id"] = action_id
        if not ok:
            data["error"] = {"code": error_code or "assistant_error", "message": message}
        return data

    def _artist_album_gap_response(self, message: str, conversation_id: int | None = None) -> dict[str, Any] | None:
        """Deterministic path for “某艺人的专辑还有哪些没入库”.

        This intent was prone to MiniMax returning raw pseudo tool blocks.  A
        direct local+PT workflow is more reliable and gives the user the exact
        comparison they asked for.
        """
        match = re.search(r"(?:音乐库|曲库)中\s*([^的，。！？?\s]{1,24})\s*的专辑.*?(?:没有|没进|未入库|缺)", message)
        if not match:
            match = re.search(r"([^，。！？?\s]{1,40})\s*的专辑.*?(?:没有|没进|未入库|缺)", message)
        if not match:
            return None
        artist = match.group(1).strip("的 在")
        # Remove natural-language prefixes captured by the broad fallback, e.g.
        # “帮我查一下刘德华的专辑还有哪些没进库”.
        artist = re.sub(r"^(帮我|麻烦|请|查一下|看一下|看下|看看|找一下|找下|查|看|找|我想知道)", "", artist)
        if "音乐库中" in artist:
            artist = artist.split("音乐库中")[-1]
        if "曲库中" in artist:
            artist = artist.split("曲库中")[-1]
        artist = artist.strip("的 在")
        if not artist or len(artist) > 24:
            return None

        conv = self.db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first() if conversation_id else None
        if not conv:
            conv = self.create_conversation(message[:40])
        self._save_message(conv.id, "user", message)

        like = f"%{artist}%"
        rows = self.db.query(MusicFile).filter(
            (MusicFile.artist.ilike(like)) | (MusicFile.album_artist.ilike(like)) | (MusicFile.album.ilike(like))
        ).all()
        album_counts: dict[str, int] = {}
        for row in rows:
            album = (row.album or "未知专辑").strip()
            album_counts[album] = album_counts.get(album, 0) + 1
        local_norm = {_norm_album_name(name) for name in album_counts}

        tool_events: list[dict[str, Any]] = [{"name": "search_library", "args": {"keyword": artist}, "risk": "low", "status": "done", "result": {"album_count": len(album_counts)}}]
        pt_items: list[dict[str, Any]] = []
        pt_error = ""
        try:
            pt = execute_tool(self.db, "search_pt", {"keyword": f"{artist} 专辑", "limit": 20})
            compact = _compact_tool_result("search_pt", pt)
            pt_items = (compact.get("items") or compact.get("candidates") or [])[:20]
            tool_events.append({"name": "search_pt", "args": {"keyword": f"{artist} 专辑", "limit": 20}, "risk": "low", "status": "done", "result": {"count": len(pt_items)}})
        except Exception as exc:
            pt_error = _sanitize_error(exc, cfg_module.config.assistant.provider.api_key)[:160]
            tool_events.append({"name": "search_pt", "args": {"keyword": f"{artist} 专辑", "limit": 20}, "risk": "low", "status": "failed", "result": {"error": pt_error}})

        missing: list[dict[str, Any]] = []
        artist_norm = _norm_album_name(artist)
        for item in pt_items:
            title = item.get("title") or item.get("name") or item.get("subtitle") or ""
            norm_title = _norm_album_name(title)
            if not title or artist_norm not in norm_title:
                continue
            if any(album and album in norm_title for album in local_norm):
                continue
            missing.append(item)
            if len(missing) >= 8:
                break

        lines = [f"我查了本地音乐库里 **{artist}** 的专辑。"]
        if album_counts:
            lines.append("\n已入库：")
            for album, count in sorted(album_counts.items(), key=lambda x: x[0])[:12]:
                lines.append(f"- {album}（{count} 首）")
        else:
            lines.append("\n本地库里暂时没找到明确匹配的专辑。")

        if missing:
            lines.append("\nPT 搜索里看起来可能还没入库的候选：")
            for idx, item in enumerate(missing[:8], 1):
                title = item.get("title") or item.get("name") or "未命名资源"
                site = item.get("site") or item.get("source") or "-"
                size = item.get("size_gb") or item.get("size") or "-"
                seeders = item.get("seeders") or item.get("seed") or item.get("seeds") or 0
                lines.append(f"{idx}. {title} · {site} · {size}GB · 做种 {seeders}")
            lines.append("\n如果你要，我可以继续帮你从这些候选里挑最值得下载的版本。")
        elif pt_error:
            lines.append(f"\nPT 搜索暂时失败：{pt_error}")
        else:
            lines.append("\nPT 搜索结果里暂时没有明显可判定为缺失的专辑候选。")

        reply = "\n".join(lines)
        self._save_message(conv.id, "assistant", reply)
        return self._chat_response(conv.id, reply, tool_calls=tool_events)

    def _shortcut_response(self, message: str, conversation_id: int | None = None) -> dict[str, Any] | None:
        """Fast deterministic replies for notification buttons / common shortcuts.

        These commands come from Telegram notification buttons and should not need
        a model round-trip. They intentionally stay read-only except for asking
        the user to run an existing guarded flow.
        """
        raw_text = (message or "").strip()
        album_gap = self._artist_album_gap_response(raw_text, conversation_id)
        if album_gap:
            return album_gap
        text = raw_text.lower()
        parts = text.split()
        slash_cmd = parts[0] if parts else ""
        slash_arg = " ".join(parts[1:]).strip()
        aliases = {
            "/tasks": "tasks", "/task": "tasks", "查看任务": "tasks", "任务": "tasks", "打开任务": "tasks", "下载任务": "tasks", "任务状态": "tasks",
            "/library": "library", "/lib": "library", "打开音乐库": "library", "音乐库": "library", "查看音乐库": "library", "曲库": "library",
            "/health": "health", "曲库状态": "health", "音乐库状态": "health", "帮我看看曲库状态": "health", "看看曲库状态": "health",
            "打开治理": "health", "治理": "health", "音乐库治理": "health", "曲库治理": "health",
            "/cleanup": "cleanup", "清理扫描": "cleanup", "执行清理扫描": "cleanup",
            "/status": "status", "状态": "status", "系统状态": "status",
            "/help": "help", "帮助": "help", "快捷指令": "help",
        }
        kind = aliases.get(slash_cmd) if slash_cmd.startswith("/") else aliases.get(text)
        if not kind:
            return None
        conv = self.db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first() if conversation_id else None
        if not conv:
            conv = self.create_conversation((message or "快捷指令")[:40])
        self._save_message(conv.id, "user", message)

        if kind == "tasks":
            task_args: dict[str, Any] = {"limit": 8}
            if slash_arg in {"pending", "downloading", "downloaded", "organized", "scraped", "completed", "paused", "missing", "failed"}:
                task_args["status"] = slash_arg
            elif slash_arg:
                task_args["keyword"] = slash_arg
            result = execute_tool(self.db, "list_tasks", task_args)
            items = result.get("items") or []
            if not items:
                reply = "当前没有下载任务。"
            else:
                lines = ["最近下载任务："]
                for item in items[:8]:
                    lines.append(f"#{item.get('id')} · {item.get('status') or '-'} · {item.get('name') or '-'}")
                reply = "\n".join(lines)
        elif kind == "library":
            result = execute_tool(self.db, "get_library_stats", {})
            reply = (
                "音乐库概览：\n"
                f"曲目：{result.get('tracks', 0)}\n"
                f"专辑：{result.get('albums', 0)}\n"
                f"总时长：{result.get('total_hours', 0)} 小时\n"
                f"格式：{', '.join(f'{k}:{v}' for k, v in (result.get('formats') or {}).items()) or '-'}"
            )
        elif kind == "health":
            health_kind = slash_arg if slash_arg in {"missing_cover", "missing_lyrics", "missing_duration", "unknown_artist", "unscraped", "cue_candidates", "album_artist_conflicts", "split_album_folders"} else ""
            result = execute_tool(self.db, "query_library_health", {"kind": health_kind, "limit": 5})
            totals = result.get("totals") or {}
            labels = {
                "missing_cover": "缺封面", "missing_lyrics": "缺歌词", "missing_duration": "缺时长",
                "unknown_artist": "未知艺人", "unscraped": "未刮削", "cue_candidates": "CUE候选",
                "album_artist_conflicts": "专辑艺人冲突", "split_album_folders": "同专辑分裂",
            }
            if health_kind:
                items = result.get("items") or []
                lines = [f"{labels.get(health_kind, health_kind)}：{result.get('total', 0)}"]
                for item in items[:5]:
                    lines.append(f"- {item.get('artist') or '-'} / {item.get('album') or '-'} · {item.get('track_count') or item.get('total_tracks') or 0} 首")
                reply = "\n".join(lines)
            elif not totals:
                reply = "音乐库治理状态正常，暂未发现明显问题。"
            else:
                lines = ["音乐库治理概览："]
                for key, val in totals.items():
                    if val:
                        lines.append(f"{labels.get(key, key)}：{val}")
                reply = "\n".join(lines) if len(lines) > 1 else "音乐库治理状态正常。"
        elif kind == "status":
            result = execute_tool(self.db, "get_system_status", {})
            reply = (
                "Music Sub 状态：\n"
                f"版本：{result.get('version') or '-'}\n"
                f"站点：{len(result.get('sites_enabled') or [])} 个启用\n"
                f"曲库：{result.get('library_files', 0)} 首\n"
                f"订阅：{result.get('subscriptions', 0)} 个\n"
                f"任务：{result.get('tasks', 0)} 个"
            )
        elif kind == "help":
            reply = "快捷指令：\n/tasks 最近任务；/tasks failed 查失败任务；/tasks 关键词 搜任务\n/library 曲库概览\n/health 曲库治理；/health missing_lyrics 查某类问题\n/cleanup 清理扫描入口\n/status 系统状态\n也可以直接说：搜索周杰伦 FLAC、下载第一个、补齐某张专辑。"
        else:  # cleanup
            result = execute_tool(self.db, "list_tasks", {"limit": 8})
            items = result.get("items") or []
            reply = "清理扫描入口在任务页。最近任务："
            if items:
                reply += "\n" + "\n".join(f"#{i.get('id')} · {i.get('status')} · {i.get('name')}" for i in items[:5])
            else:
                reply += "暂无任务。"
            reply += "\n\n如果要执行清理，请到 Web 端任务页确认；涉及删除/清理的动作仍需要显式确认。"

        self._save_message(conv.id, "assistant", reply)
        return self._chat_response(conv.id, reply, tool_calls=[{"name": f"shortcut:{kind}", "status": "done", "risk": "low"}])

    def chat(self, message: str, conversation_id: int | None = None) -> dict[str, Any]:
        cfg = cfg_module.config.assistant
        message = (message or "").strip()
        if not message:
            return self._chat_response(conversation_id or 0, "请输入要发送给助手的内容。", ok=False, error_code="empty_message")
        shortcut = self._shortcut_response(message, conversation_id)
        if shortcut:
            return shortcut
        if not cfg.enabled:
            return self._chat_response(conversation_id or 0, "智能助手未启用，请先到设置里开启 Assistant。", ok=False, error_code="assistant_disabled")
        conv = self.db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first() if conversation_id else None
        if not conv:
            conv = self.create_conversation((message or "新对话")[:40])
        self._save_message(conv.id, "user", message)

        messages = self._history_for_llm(conv.id)
        client = self._llm_client()
        tool_events: list[dict[str, Any]] = []

        try:
            tool_loop_counts: dict[str, int] = {}
            for _ in range(max(1, min(int(getattr(cfg, "max_iterations", 4) or 4), 32))):
                assistant_msg = client.chat(messages, tools=openai_tools(self._enabled_tool_names()))
                tool_calls = assistant_msg.get("tool_calls") or []
                if not tool_calls:
                    raw_content = assistant_msg.get("content") or "我查到了，但模型没有生成文字总结。"
                    content = _clean_assistant_output(raw_content)
                    if _looks_like_tool_leak(raw_content) and not content:
                        content = "我刚才拿到了中间工具格式，但模型没有生成可读总结。已拦截原始输出，请再发一次或换个说法，我会重新用工具查询。"
                    content = self._append_verbose_summary(content, tool_events)
                    self._save_message(conv.id, "assistant", content)
                    return self._chat_response(conv.id, content, tool_calls=tool_events)

                messages.append(assistant_msg)
                for call in tool_calls[:5]:
                    outcome = self._execute_or_request_confirm(conv.id, call, messages, tool_events, tool_loop_counts)
                    if outcome:
                        return outcome

            text = f"这次调用工具步骤超过上限（{getattr(cfg, 'max_iterations', 4)} 轮），我先暂停一下。请确认下一步要继续搜索、下载还是整理。"
            self._save_message(conv.id, "assistant", text)
            return self._chat_response(conv.id, text, tool_calls=tool_events)
        except AssistantLLMError as e:
            text = str(e)
            self._save_message(conv.id, "assistant", text, status="failed")
            return self._chat_response(conv.id, text, ok=False, error_code="llm_error", tool_calls=tool_events)
        except Exception as e:
            logger.exception("assistant chat failed")
            text = f"助手执行失败：{_sanitize_error(e, cfg.provider.api_key)}"
            self._save_message(conv.id, "assistant", text, status="failed")
            return self._chat_response(conv.id, text, ok=False, error_code="assistant_error", tool_calls=tool_events)

    def _run_tool_with_timeout(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        timeout = max(5, min(int(getattr(cfg_module.config.assistant, "tool_timeout_seconds", 120) or 120), 600))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(execute_tool, self.db, name, args)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise TimeoutError(f"工具调用超时（{timeout}s）：{name}") from exc

    def _append_verbose_summary(self, content: str, tool_events: list[dict[str, Any]]) -> str:
        if not getattr(cfg_module.config.assistant, "verbose", False) or not tool_events:
            return content
        lines = [content.rstrip(), "", "---", "工具调用摘要："]
        for event in tool_events[:10]:
            status = event.get("status") or "-"
            name = event.get("name") or "unknown"
            risk = event.get("risk") or "-"
            lines.append(f"- {name} · {status} · risk={risk}")
        return "\n".join(lines).strip()

    def _execute_or_request_confirm(self, conversation_id: int, call: dict[str, Any], messages: list[dict[str, Any]], tool_events: list[dict[str, Any]], tool_loop_counts: dict[str, int] | None = None) -> dict[str, Any] | None:
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            args = {}
            result = {"ok": False, "error": f"工具参数不是合法 JSON：{_truncate_text(str(raw_args), 300)}"}
            tool_events.append({"name": name or "unknown", "args": {}, "result": result, "risk": "high", "status": "failed"})
            self._save_message(conversation_id, "tool", tool_name=name, tool_args_json="{}", tool_result_json=_json_dumps(result), status="failed")
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _json_dumps(result)})
            return None
        risk = tool_risk(name)
        signature = _tool_signature(name, args)
        if tool_loop_counts is not None:
            tool_loop_counts[signature] = tool_loop_counts.get(signature, 0) + 1
            if tool_loop_counts[signature] >= 3:
                result = {
                    "ok": False,
                    "error": "检测到重复工具调用，已停止继续重试。请根据已有结果给用户结论，或说明需要用户补充信息。",
                    "tool": name,
                    "loop_count": tool_loop_counts[signature],
                }
                tool_events.append({"name": name, "args": args, "result": result, "risk": risk, "status": "blocked_loop"})
                self._save_message(conversation_id, "tool", tool_name=name, tool_args_json=_json_dumps(args), tool_result_json=_json_dumps(result), status="blocked_loop")
                messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _json_dumps(result)})
                return None
        allowed, reason = self._tool_allowed(name)
        if not allowed:
            text = f"当前设置不允许执行：{name}。{reason}"
            self._save_message(conversation_id, "assistant", text, status="failed")
            return self._chat_response(conversation_id, text, ok=False, error_code="tool_not_allowed")
        if self._requires_confirm(name, risk, args):
            action_id = self._create_action(conversation_id, name, args, risk)
            summary = self._action_summary(name, args, risk)
            preview = self._action_preview(name, args, risk, summary)
            text = f"需要确认后才能执行：{summary}"
            self._save_message(conversation_id, "assistant", text, status="needs_confirm")
            tool_call = {"id": action_id, "name": name, "args": args, "risk": risk, "summary": summary, "preview": preview, "requires_confirm": True}
            return self._chat_response(conversation_id, text, tool_calls=[tool_call], needs_confirm=True, action_id=action_id)
        try:
            result = self._run_tool_with_timeout(name, args)
            compact_result = _compact_tool_result(name, result)
            tool_events.append({"name": name, "args": args, "result": compact_result, "risk": risk, "status": "done"})
            self._save_message(
                conversation_id,
                "tool",
                tool_name=name,
                tool_call_id=call.get("id"),
                tool_args_json=_json_dumps(args),
                tool_result_json=_json_dumps(result),
            )
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _json_dumps(compact_result)})
        except Exception as e:
            logger.exception("assistant tool failed: %s", name)
            result = {"ok": False, "error": _sanitize_error(e, cfg_module.config.assistant.provider.api_key), "tool": name}
            tool_events.append({"name": name, "args": args, "result": result, "risk": risk, "status": "failed"})
            self._save_message(
                conversation_id,
                "tool",
                tool_name=name,
                tool_call_id=call.get("id"),
                tool_args_json=_json_dumps(args),
                tool_result_json=_json_dumps(result),
                status="failed",
            )
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _json_dumps(result)})
        return None

    def _tool_allowed(self, name: str) -> tuple[bool, str]:
        cfg = cfg_module.config.assistant
        enabled_tools = self._enabled_tool_names()
        if enabled_tools and name not in enabled_tools:
            return False, f"工具 {name} 已在设置中禁用。"
        if name in {"download_online_song", "complete_album"} and not cfg.allow_online_download:
            return False, "请先在设置中打开“允许在线音乐下载工具”。"
        if name in {"rescrape_album", "organize_task", "complete_album"} and not cfg.allow_library_write:
            return False, "请先在设置中打开“允许音乐库写入工具”。"
        if name in {"delete_task", "delete_qb_task"} and not cfg.allow_task_delete:
            return False, "请先在设置中打开“允许任务删除工具”。"
        return True, ""

    def _requires_confirm(self, name: str, risk: str, args: dict[str, Any] | None = None) -> bool:
        cfg = cfg_module.config.assistant
        args = args or {}
        if name in {"download_torrent", "download_online_song"}:
            return cfg.require_confirm_for_download
        if name == "complete_album":
            # Preview is read-only; actual downloading must follow download confirmation.
            return bool(args.get("dry_run") is False) and cfg.require_confirm_for_download
        if name in {"delete_task", "delete_qb_task"}:
            return cfg.require_confirm_for_delete
        if risk == "high":
            return True
        if risk == "medium":
            return cfg.require_confirm_for_apply_tools
        return False

    def _action_summary(self, name: str, args: dict[str, Any], risk: str) -> str:
        if name == "download_torrent":
            return f"下载 PT 资源《{args.get('title') or args.get('torrent_id')}》（{args.get('site')}）"
        if name == "download_online_song":
            song = args.get("song") or {}
            return f"下载在线音乐《{song.get('title') or song.get('filename') or '未知歌曲'}》 - {song.get('artist') or '未知艺人'}（{song.get('source') or 'online'}）"
        if name == "create_subscription":
            return f"创建订阅：{args.get('keyword')}（{args.get('type') or 'artist'} / {args.get('quality') or 'any'}）"
        if name == "organize_task":
            return f"整理任务 #{args.get('task_id')} 并入库"
        if name == "rescrape_album":
            return f"重新刮削专辑：{args.get('artist')} - {args.get('album')}"
        if name == "complete_album":
            mode = "下载补齐" if args.get("dry_run") is False else "预览补齐"
            return f"{mode}专辑：{args.get('artist')} - {args.get('album')}"
        if name == "query_library_health":
            return f"查询音乐库治理问题：{args.get('kind') or '全部'}"
        if name == "read_recent_logs":
            return f"读取最近日志：{args.get('level') or 'ALL'} / {args.get('lines') or 120} 行"
        if name in {"pause_task", "resume_task"}:
            return f"{name}：任务 #{args.get('task_id')}"
        return f"{name}（风险级别：{risk}）"

    def _action_preview(self, name: str, args: dict[str, Any], risk: str, summary: str) -> dict[str, Any]:
        details: list[dict[str, str]] = []
        effect = "执行后会修改 Music Sub 状态。"
        if name == "download_torrent":
            details = [
                {"label": "资源", "value": str(args.get("title") or args.get("torrent_id") or "-")},
                {"label": "站点", "value": str(args.get("site") or "-")},
                {"label": "Torrent ID", "value": str(args.get("torrent_id") or "-")},
            ]
            effect = "确认后会下载种子并添加到 qBittorrent，随后任务页会出现新下载任务。"
        elif name == "download_online_song":
            song = args.get("song") or {}
            details = [
                {"label": "歌曲", "value": str(song.get("title") or song.get("filename") or "-")},
                {"label": "艺人", "value": str(song.get("artist") or "-")},
                {"label": "来源", "value": str(song.get("source") or "-")},
                {"label": "整理入库", "value": "是" if args.get("organize", True) else "否"},
            ]
            effect = "确认后会下载音频文件；若开启整理，会自动进入整理/刮削流程。"
        elif name == "create_subscription":
            details = [
                {"label": "关键词", "value": str(args.get("keyword") or "-")},
                {"label": "类型", "value": str(args.get("type") or "artist")},
                {"label": "质量", "value": str(args.get("quality") or "any")},
                {"label": "站点", "value": str(args.get("sites") or "all")},
            ]
            effect = "确认后会新增订阅，后续定时任务会自动搜索匹配资源。"
        elif name == "organize_task":
            details = [{"label": "任务 ID", "value": str(args.get("task_id") or "-")}]
            effect = "确认后会对该下载任务执行整理、硬链接/复制和元数据刮削。"
        elif name == "rescrape_album":
            details = [
                {"label": "艺人", "value": str(args.get("artist") or "-")},
                {"label": "专辑", "value": str(args.get("album") or "-")},
            ]
            effect = "确认后会启动专辑重新刮削后台任务。"
        elif name == "complete_album":
            details = [
                {"label": "艺人", "value": str(args.get("artist") or "-")},
                {"label": "专辑", "value": str(args.get("album") or "-")},
                {"label": "模式", "value": "下载并入库" if args.get("dry_run") is False else "只预览候选"},
                {"label": "上限", "value": str(args.get("limit") or 40)},
            ]
            effect = "dry_run=true 只搜索候选；dry_run=false 会在线下载缺失曲目并自动整理入库。"
        elif name in {"pause_task", "resume_task"}:
            details = [{"label": "任务 ID", "value": str(args.get("task_id") or "-")}]
            effect = "确认后会修改 qBittorrent 下载状态。"
        return {"summary": summary, "risk": risk, "details": details, "effect": effect}

    def _create_action(self, conversation_id: int, tool_name: str, args: dict[str, Any], risk: str) -> str:
        action_id = uuid.uuid4().hex[:16]
        action = AssistantAction(
            action_id=action_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            tool_args_json=_json_dumps(args),
            risk=risk,
            status="pending",
        )
        self.db.add(action)
        self.db.commit()
        return action_id

    def _result_items_for_action(self, message: AssistantMessage) -> list[dict[str, Any]]:
        result = _safe_json_loads(message.tool_result_json)
        if isinstance(result.get("candidates"), list):
            return result.get("candidates") or []
        if isinstance(result.get("items"), list):
            return result.get("items") or []
        if message.tool_name == "complete_album" and isinstance(result.get("downloaded"), list):
            return result.get("downloaded") or []
        return []

    def _derive_action_from_result_item(self, message: AssistantMessage, item: dict[str, Any], action_key: str) -> tuple[str, dict[str, Any]]:
        action_key = (action_key or "download").strip()
        title = str(item.get("title") or item.get("name") or item.get("keyword") or "").strip()
        artist = str(item.get("artist") or item.get("album_artist") or item.get("suggested_album_artist") or "").strip()
        album = str(item.get("album") or item.get("suggested_album") or "").strip()
        if action_key in {"download", "direct-tool"}:
            if item.get("download_tool") and isinstance(item.get("download_args"), dict):
                return str(item.get("download_tool")), item.get("download_args") or {}
            if message.tool_name == "search_pt":
                return "download_torrent", {"site": item.get("site"), "torrent_id": item.get("torrent_id"), "title": item.get("title")}
            if message.tool_name in {"search_online", "complete_album"}:
                return "download_online_song", {"song": item, "organize": True}
        if action_key in {"search-pt", "search_pt"}:
            keyword = " ".join(x for x in [title, artist, album] if x).strip()
            if not keyword:
                raise ValueError("缺少 PT 搜索关键词")
            return "search_pt", {"keyword": keyword, "limit": 10}
        if action_key in {"subscribe-keyword", "subscribe"}:
            keyword = " ".join(x for x in [title, artist] if x).strip() or album or artist
            if not keyword:
                raise ValueError("缺少可订阅关键词")
            return "create_subscription", {"keyword": keyword, "type": "keyword", "quality": "flac", "sites": "all", "enabled": True}
        if action_key == "subscribe-song":
            keyword = " ".join(x for x in [title, artist] if x).strip()
            if not keyword:
                raise ValueError("缺少歌曲订阅关键词")
            return "create_subscription", {"keyword": keyword, "type": "keyword", "quality": "flac", "sites": "all", "enabled": True}
        if action_key == "rescrape-album":
            if not (artist and album):
                raise ValueError("缺少艺人或专辑名，无法重刮专辑")
            return "rescrape_album", {"artist": artist, "album": album}
        if action_key == "complete-album-preview":
            if not (artist and album):
                raise ValueError("缺少艺人或专辑名，无法预览补齐")
            return "complete_album", {"artist": artist, "album": album, "dry_run": True, "limit": 40}
        if action_key == "complete-album-download":
            if not (artist and album):
                raise ValueError("缺少艺人或专辑名，无法下载补齐")
            return "complete_album", {"artist": artist, "album": album, "dry_run": False, "limit": 40}
        raise ValueError("该结果暂不支持直接动作")

    def prepare_action_from_result(self, message_id: int, item_index: int, action_key: str = "download") -> dict[str, Any]:
        """Prepare an action from a persisted tool-result item.

        This is the lightweight Pending Interaction path: the client sends only
        message_id + item index + action, and the server derives trusted tool args
        from the stored tool result instead of accepting a large JSON blob back
        from the browser/chat surface.
        """
        message = self.db.query(AssistantMessage).filter(AssistantMessage.id == int(message_id), AssistantMessage.role == "tool").first()
        if not message:
            return self._chat_response(0, "工具结果不存在或已过期。", ok=False, error_code="result_not_found")
        items = self._result_items_for_action(message)
        if item_index < 0 or item_index >= len(items):
            return self._chat_response(message.conversation_id, "结果序号无效或已过期。", ok=False, error_code="result_index_invalid")
        try:
            tool_name, args = self._derive_action_from_result_item(message, items[item_index], action_key)
        except Exception as exc:
            return self._chat_response(message.conversation_id, str(exc), ok=False, error_code="unsupported_result_action")
        return self.prepare_action(tool_name, args, message.conversation_id)

    def prepare_action(self, tool_name: str, args: dict[str, Any], conversation_id: int | None = None) -> dict[str, Any]:
        """Create or execute a direct UI action without another model round-trip."""
        tool_name = (tool_name or "").strip()
        args = args or {}
        conv = self.db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first() if conversation_id else None
        if not conv:
            conv = self.create_conversation("快捷操作")
        risk = tool_risk(tool_name)
        allowed, reason = self._tool_allowed(tool_name)
        if not allowed:
            text = f"当前设置不允许执行：{tool_name}。{reason}"
            self._save_message(conv.id, "assistant", text, status="failed")
            return self._chat_response(conv.id, text, ok=False, error_code="tool_not_allowed")
        summary = self._action_summary(tool_name, args, risk)
        preview = self._action_preview(tool_name, args, risk, summary)
        if self._requires_confirm(tool_name, risk, args):
            action_id = self._create_action(conv.id, tool_name, args, risk)
            text = f"需要确认后才能执行：{summary}"
            self._save_message(conv.id, "assistant", text, status="needs_confirm")
            tool_call = {"id": action_id, "name": tool_name, "args": args, "risk": risk, "summary": summary, "preview": preview, "requires_confirm": True}
            return self._chat_response(conv.id, text, tool_calls=[tool_call], needs_confirm=True, action_id=action_id)
        try:
            result = self._run_tool_with_timeout(tool_name, args)
            self._save_message(conv.id, "tool", tool_name=tool_name, tool_args_json=_json_dumps(args), tool_result_json=_json_dumps(result))
            text = self._tool_success_message(tool_name, args, result)
            self._save_message(conv.id, "assistant", text)
            return self._chat_response(conv.id, text, tool_calls=[{"name": tool_name, "args": args, "risk": risk, "status": "done", "result": _compact_tool_result(tool_name, result)}])
        except Exception as e:
            logger.exception("assistant prepared action failed: %s", tool_name)
            safe_error = _sanitize_error(e, cfg_module.config.assistant.provider.api_key)
            text = f"执行失败：{tool_name}。原因：{safe_error}"
            self._save_message(conv.id, "assistant", text, status="failed")
            return self._chat_response(conv.id, text, ok=False, error_code="tool_error")

    def confirm_action(self, action_id: str) -> dict[str, Any]:
        action = self.db.query(AssistantAction).filter(AssistantAction.action_id == action_id).first()
        if not action:
            return {"ok": False, "message": "操作不存在或已过期"}
        if action.status != "pending":
            return {"ok": False, "message": f"操作已处理：{action.status}"}
        args = _safe_json_loads(action.tool_args_json)
        allowed, reason = self._tool_allowed(action.tool_name)
        if not allowed:
            return {"ok": False, "message": reason}
        try:
            result = self._run_tool_with_timeout(action.tool_name, args)
            action.status = "done"
            action.result_json = _json_dumps(result)
            action.updated_at = datetime.datetime.utcnow()
            self._save_message(
                action.conversation_id,
                "tool",
                tool_name=action.tool_name,
                tool_args_json=action.tool_args_json,
                tool_result_json=action.result_json,
            )
            text = self._tool_success_message(action.tool_name, args, result)
            preview = self._action_preview(action.tool_name, args, action.risk, self._action_summary(action.tool_name, args, action.risk))
            self._save_message(action.conversation_id, "assistant", text)
            self.db.commit()
            return {"ok": True, "message": text, "result": result, "preview": preview}
        except Exception as e:
            logger.exception("assistant confirmed action failed: %s", action.tool_name)
            safe_error = _sanitize_error(e, cfg_module.config.assistant.provider.api_key)
            action.status = "failed"
            action.result_json = _json_dumps({"error": safe_error})
            action.updated_at = datetime.datetime.utcnow()
            text = f"执行失败：{action.tool_name}。原因：{safe_error}"
            self._save_message(action.conversation_id, "assistant", text, status="failed")
            self.db.commit()
            return {"ok": False, "message": safe_error, "error": {"code": "tool_error", "message": safe_error}}

    def _tool_success_message(self, name: str, args: dict[str, Any], result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return f"已执行：{name}。"
        if name == "download_torrent":
            if result.get("already_exists"):
                return f"任务已存在：#{result.get('task_id')}，没有重复添加。"
            return f"已添加下载任务：#{result.get('task_id')}《{result.get('title') or args.get('title') or args.get('torrent_id')}》。你可以到任务列表查看进度。"
        if name == "download_online_song":
            return f"已下载在线音乐并创建任务：#{result.get('task_id')}。文件：{result.get('file_path') or '-'}；整理入库：{'是' if result.get('organized') else '否'}。"
        if name == "create_subscription":
            sub = result.get("subscription") or {}
            return f"已创建订阅：#{sub.get('id')} {sub.get('keyword')}（{sub.get('type')} / {sub.get('quality')} / {sub.get('sites')}）。"
        if name == "organize_task":
            return f"已提交整理任务：#{result.get('task_id')}，状态：{result.get('status') or 'ok'}。"
        if name == "rescrape_album":
            if result.get("job_id"):
                return f"已提交重新刮削后台任务：{result.get('job_id')}，共 {result.get('total', 1)} 张专辑。"
            return "已执行专辑重新刮削。"
        if name == "complete_album":
            if result.get("dry_run"):
                return f"已预览专辑补齐：本地已有 {result.get('existing', 0)} 首，找到 {len(result.get('candidates') or [])} 首疑似缺失候选。"
            return f"已执行专辑补齐：下载 {len(result.get('downloaded') or [])} 首，失败 {len(result.get('errors') or [])} 首。"
        if name == "search_pt":
            candidates = result.get("candidates") or result.get("items") or []
            sites = result.get("sites") or []
            site_summary = "，".join(str(s.get("site") or s.get("name") or "") for s in sites[:4] if isinstance(s, dict))
            return f"已搜索 PT：找到 {len(candidates)} 个候选" + (f"；站点：{site_summary}" if site_summary else "。")
        if name == "search_online":
            candidates = result.get("candidates") or result.get("items") or []
            return f"已搜索在线音乐：找到 {len(candidates)} 个候选。"
        if name == "search_download_candidates":
            candidates = result.get("candidates") or []
            pt_total = len(((result.get("pt") or {}).get("candidates") or []))
            online_total = len(((result.get("online") or {}).get("candidates") or []))
            return f"已搜索下载候选：共 {len(candidates)} 个（PT {pt_total} / 在线 {online_total}）。"
        if name == "list_tasks":
            return f"已查询任务：共 {result.get('total', len(result.get('items') or []))} 条，返回 {len(result.get('items') or [])} 条。"
        if name == "query_library_health":
            if "totals" in result:
                total = sum(int(v or 0) for v in (result.get("totals") or {}).values())
                return f"已查询曲库治理概览：共 {total} 个问题计数。"
            return f"已查询曲库治理：{result.get('kind') or '-'} 共 {result.get('total', 0)} 条。"
        if name == "read_recent_logs":
            return f"已读取最近日志：{len(result.get('lines') or [])} 行。"
        if name == "pause_task":
            return f"已暂停任务：#{result.get('task_id')}。"
        if name == "resume_task":
            return f"已继续任务：#{result.get('task_id')}。"
        return f"已执行：{name}。"

    def cancel_action(self, action_id: str) -> dict[str, Any]:
        action = self.db.query(AssistantAction).filter(AssistantAction.action_id == action_id).first()
        if not action:
            return {"ok": False, "message": "操作不存在或已过期"}
        action.status = "cancelled"
        action.updated_at = datetime.datetime.utcnow()
        self.db.commit()
        self._save_message(action.conversation_id, "assistant", f"已取消：{action.tool_name}。")
        return {"ok": True}
