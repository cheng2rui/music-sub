"""Assistant API routes."""
import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.assistant.service import AssistantService

router = APIRouter()


class AssistantChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str


class AssistantConversationCreate(BaseModel):
    title: str = "新对话"


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
    return AssistantService(db).chat(req.message, req.conversation_id)


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: str, db: Session = Depends(get_db)):
    return AssistantService(db).confirm_action(action_id)


@router.post("/actions/{action_id}/cancel")
def cancel_action(action_id: str, db: Session = Depends(get_db)):
    return AssistantService(db).cancel_action(action_id)
