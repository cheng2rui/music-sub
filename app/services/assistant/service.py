"""Assistant orchestration service."""
from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app import config as cfg_module
from app.models import AssistantAction, AssistantConversation, AssistantMessage
from app.services.assistant.llm import AssistantLLMClient, AssistantLLMError
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


def _compact_tool_result(tool_name: str, result: Any) -> Any:
    """Keep full tool results in DB, but feed only compact data back to the LLM.

    This follows MoviePilot's pattern: tool output should be useful for the next
    decision, not pollute the whole conversation context.
    """
    if not isinstance(result, dict):
        return result
    if tool_name == "search_pt":
        return {
            "queries": result.get("queries") or [],
            "sites": result.get("sites") or [],
            "items": (result.get("items") or [])[:8],
            "instruction": result.get("instruction") or "",
        }
    if tool_name == "search_online":
        return {"items": (result.get("items") or [])[:6]}
    if tool_name in {"list_tasks", "list_subscriptions", "search_library"}:
        return {"items": (result.get("items") or [])[:15]}
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
        return {
            "enabled": cfg.enabled,
            "provider": cfg.provider.provider,
            "model": cfg.provider.model,
            "tools": [t["function"]["name"] for t in tools],
            "tool_catalog": tool_catalog(enabled_tools),
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
        rows = self.get_messages(conversation_id)[-(cfg.max_history_messages or 20):]
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for row in rows:
            if row.role in {"user", "assistant"}:
                messages.append({"role": row.role, "content": row.content or ""})
            elif row.role == "tool":
                # Persisted tool messages are replayed as plain assistant context instead
                # of protocol-level `tool` messages. OpenAI/Anthropic both require a
                # preceding assistant tool_call/tool_use in the same request; after a
                # page reload or a later user turn we only need the data as context.
                raw_result = _safe_json_loads(row.tool_result_json) if row.tool_result_json else {}
                result = _json_dumps(_compact_tool_result(row.tool_name or "", raw_result)) if raw_result else (row.content or "{}")
                messages.append({"role": "assistant", "content": f"[工具结果 {row.tool_name or ''}]\n{_truncate_text(result)}"})
        return messages

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
        )

    def chat(self, message: str, conversation_id: int | None = None) -> dict[str, Any]:
        cfg = cfg_module.config.assistant
        if not cfg.enabled:
            return {"conversation_id": conversation_id or 0, "message": "智能助手未启用，请先到设置里开启 Assistant。", "tool_calls": [], "needs_confirm": False}
        conv = self.db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first() if conversation_id else None
        if not conv:
            conv = self.create_conversation((message or "新对话")[:40])
        self._save_message(conv.id, "user", message)

        messages = self._history_for_llm(conv.id)
        client = self._llm_client()
        tool_events: list[dict[str, Any]] = []

        try:
            for _ in range(4):
                assistant_msg = client.chat(messages, tools=openai_tools(self._enabled_tool_names()))
                tool_calls = assistant_msg.get("tool_calls") or []
                if not tool_calls:
                    content = assistant_msg.get("content") or "我查到了，但模型没有生成文字总结。"
                    self._save_message(conv.id, "assistant", content)
                    return {"conversation_id": conv.id, "message": content, "tool_calls": tool_events, "needs_confirm": False}

                messages.append(assistant_msg)
                for call in tool_calls[:5]:
                    outcome = self._execute_or_request_confirm(conv.id, call, messages, tool_events)
                    if outcome:
                        return outcome

            text = "这次调用的工具步骤太多，我先暂停一下。请确认下一步要继续搜索、下载还是整理。"
            self._save_message(conv.id, "assistant", text)
            return {"conversation_id": conv.id, "message": text, "tool_calls": tool_events, "needs_confirm": False}
        except AssistantLLMError as e:
            text = str(e)
            self._save_message(conv.id, "assistant", text, status="failed")
            return {"conversation_id": conv.id, "message": text, "tool_calls": tool_events, "needs_confirm": False}
        except Exception as e:
            logger.exception("assistant chat failed")
            text = f"助手执行失败：{e}"
            self._save_message(conv.id, "assistant", text, status="failed")
            return {"conversation_id": conv.id, "message": text, "tool_calls": tool_events, "needs_confirm": False}

    def _execute_or_request_confirm(self, conversation_id: int, call: dict[str, Any], messages: list[dict[str, Any]], tool_events: list[dict[str, Any]]) -> dict[str, Any] | None:
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        args = _safe_json_loads(fn.get("arguments"))
        risk = tool_risk(name)
        allowed, reason = self._tool_allowed(name)
        if not allowed:
            text = f"当前设置不允许执行：{name}。{reason}"
            self._save_message(conversation_id, "assistant", text, status="failed")
            return {"conversation_id": conversation_id, "message": text, "tool_calls": [], "needs_confirm": False}
        if self._requires_confirm(name, risk):
            action_id = self._create_action(conversation_id, name, args, risk)
            summary = self._action_summary(name, args, risk)
            preview = self._action_preview(name, args, risk, summary)
            text = f"需要确认后才能执行：{summary}"
            self._save_message(conversation_id, "assistant", text, status="needs_confirm")
            return {
                "conversation_id": conversation_id,
                "message": text,
                "tool_calls": [{"id": action_id, "name": name, "args": args, "risk": risk, "summary": summary, "preview": preview, "requires_confirm": True}],
                "needs_confirm": True,
                "action_id": action_id,
            }
        result = execute_tool(self.db, name, args)
        compact_result = _compact_tool_result(name, result)
        tool_events.append({"name": name, "args": args, "result": compact_result, "risk": risk})
        self._save_message(
            conversation_id,
            "tool",
            tool_name=name,
            tool_call_id=call.get("id"),
            tool_args_json=_json_dumps(args),
            tool_result_json=_json_dumps(result),
        )
        messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _json_dumps(compact_result)})
        return None

    def _tool_allowed(self, name: str) -> tuple[bool, str]:
        cfg = cfg_module.config.assistant
        enabled_tools = self._enabled_tool_names()
        if enabled_tools and name not in enabled_tools:
            return False, f"工具 {name} 已在设置中禁用。"
        if name == "download_online_song" and not cfg.allow_online_download:
            return False, "请先在设置中打开“允许在线音乐下载工具”。"
        if name in {"rescrape_album", "organize_task"} and not cfg.allow_library_write:
            return False, "请先在设置中打开“允许音乐库写入工具”。"
        if name in {"delete_task", "delete_qb_task"} and not cfg.allow_task_delete:
            return False, "请先在设置中打开“允许任务删除工具”。"
        return True, ""

    def _requires_confirm(self, name: str, risk: str) -> bool:
        cfg = cfg_module.config.assistant
        if name in {"download_torrent", "download_online_song"}:
            return cfg.require_confirm_for_download
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
            result = execute_tool(self.db, action.tool_name, args)
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
            action.status = "failed"
            action.result_json = _json_dumps({"error": str(e)})
            action.updated_at = datetime.datetime.utcnow()
            text = f"执行失败：{action.tool_name}。原因：{e}"
            self._save_message(action.conversation_id, "assistant", text, status="failed")
            self.db.commit()
            return {"ok": False, "message": str(e)}

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
