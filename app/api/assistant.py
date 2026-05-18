"""Assistant API routes."""
import datetime
import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
import app.config as cfg_module
from app.api.settings import _is_unchanged_mask
from app.services.assistant.service import AssistantService
from app.services.assistant.providers import list_providers
from app.services.assistant.tools import tool_catalog
from app.services.assistant.llm import AssistantLLMClient, AssistantLLMError, _sanitize_error

logger = logging.getLogger(__name__)
router = APIRouter()


class AssistantChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str


class AssistantConversationCreate(BaseModel):
    title: str = "新对话"


class AssistantProviderTestRequest(BaseModel):
    enabled: bool = True
    provider: dict = {}


def _conversation_row(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _message_row(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "role": row.role,
        "content": row.content,
        "tool_name": row.tool_name,
        "tool_args_json": row.tool_args_json,
        "tool_result_json": row.tool_result_json,
        "status": row.status,
        "created_at": row.created_at,
    }


@router.get("/capabilities")
def capabilities(db: Session = Depends(get_db)):
    return AssistantService(db).capabilities()


@router.get("/providers")
def providers():
    return {"providers": list_providers()}


@router.get("/tools")
def tools(db: Session = Depends(get_db)):
    cfg = AssistantService(db)._enabled_tool_names()
    return {"tools": tool_catalog(cfg)}


@router.get("/activity")
def activity(limit: int = 50, db: Session = Depends(get_db)):
    return {"items": AssistantService(db).recent_activity(limit)}


@router.post("/providers/test")
def test_provider(req: AssistantProviderTestRequest):
    if not req.enabled:
        return {"ok": False, "message": "请先启用智能助手"}
    provider = req.provider or {}
    if not provider.get("model"):
        return {"ok": False, "message": "请先填写模型 ID"}
    api_key = provider.get("api_key") or ""
    saved_key = cfg_module.config.assistant.provider.api_key
    if _is_unchanged_mask(api_key, saved_key, 6):
        api_key = saved_key
    if not api_key:
        return {"ok": False, "message": "请先填写 API Key"}
    try:
        client = AssistantLLMClient(
            provider=provider.get("provider") or "openai_compatible",
            runtime=provider.get("runtime") or "",
            base_url=provider.get("base_url") or "",
            api_key=api_key,
            model=provider.get("model") or "",
            temperature=float(provider.get("temperature") or 0.2),
            timeout_seconds=int(provider.get("timeout_seconds") or 30),
        )
        return client.test()
    except AssistantLLMError as e:
        return {"ok": False, "message": str(e), "error": {"code": "llm_error", "message": str(e)}}
    except Exception as e:
        logger.exception("assistant provider test failed")
        message = _sanitize_error(e, api_key)
        return {"ok": False, "message": message, "error": {"code": "provider_test_failed", "message": message}}


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    return [_conversation_row(row) for row in AssistantService(db).list_conversations()]


@router.post("/conversations")
def create_conversation(req: AssistantConversationCreate, db: Session = Depends(get_db)):
    return _conversation_row(AssistantService(db).create_conversation(req.title))


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, db: Session = Depends(get_db)):
    return [_message_row(row) for row in AssistantService(db).get_messages(conversation_id)]


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    return AssistantService(db).delete_conversation(conversation_id)


@router.post("/chat")
def chat(req: AssistantChatRequest, db: Session = Depends(get_db)):
    try:
        return AssistantService(db).chat(req.message, req.conversation_id)
    except Exception as e:
        logger.exception("assistant chat route failed")
        message = _sanitize_error(e, cfg_module.config.assistant.provider.api_key)
        return {"ok": False, "conversation_id": req.conversation_id or 0, "message": f"助手接口异常：{message}", "tool_calls": [], "needs_confirm": False, "error": {"code": "api_error", "message": message}}


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: str, db: Session = Depends(get_db)):
    try:
        return AssistantService(db).confirm_action(action_id)
    except Exception as e:
        logger.exception("assistant confirm route failed")
        message = _sanitize_error(e, cfg_module.config.assistant.provider.api_key)
        return {"ok": False, "message": message, "error": {"code": "api_error", "message": message}}


@router.post("/actions/{action_id}/cancel")
def cancel_action(action_id: str, db: Session = Depends(get_db)):
    try:
        return AssistantService(db).cancel_action(action_id)
    except Exception as e:
        logger.exception("assistant cancel route failed")
        message = _sanitize_error(e, cfg_module.config.assistant.provider.api_key)
        return {"ok": False, "message": message, "error": {"code": "api_error", "message": message}}
