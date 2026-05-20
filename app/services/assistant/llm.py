"""LLM clients for the Music Sub assistant."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from app.services.assistant.providers import resolve_provider

logger = logging.getLogger(__name__)


class AssistantLLMError(RuntimeError):
    pass


def _append_path(base_url: str, path: str) -> str:
    base = (base_url or "").rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


class AssistantLLMClient:
    def __init__(self, provider: str, runtime: str, base_url: str, api_key: str, model: str, temperature: float = 0.2, timeout_seconds: int = 60, max_context_tokens_k: int = 64, thinking_level: str = "off"):
        resolved_runtime, resolved_base_url = resolve_provider(provider, base_url)
        self.provider = provider or "openai_compatible"
        self.runtime = runtime or resolved_runtime or "openai_compatible"
        self.base_url = (base_url or resolved_base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.temperature = temperature
        self.timeout_seconds = max(5, min(int(timeout_seconds or 60), 180))
        self.max_context_tokens_k = max(4, min(int(max_context_tokens_k or 64), 1024))
        self.thinking_level = (thinking_level or "off").strip().lower()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise AssistantLLMError("智能助手还没有配置模型，请先在设置里填写 Assistant 模型配置。")
        if self.runtime == "anthropic_compatible":
            return self._chat_anthropic(messages, tools)
        return self._chat_openai(messages, tools)

    def test(self) -> dict[str, Any]:
        started = time.perf_counter()
        msg = self.chat([{"role": "user", "content": "请只回复 OK"}], tools=None)
        duration_ms = round((time.perf_counter() - started) * 1000)
        text = msg.get("content") or ""
        return {"ok": True, "provider": self.provider, "runtime": self.runtime, "model": self.model, "duration_ms": duration_ms, "reply_preview": text[:120]}

    def _chat_openai(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        max_tokens = max(1024, min(self.max_context_tokens_k * 1024 // 4, 8192))
        payload["max_tokens"] = max_tokens
        if self.thinking_level and self.thinking_level != "off":
            payload["extra_body"] = {"thinking": {"type": "enabled", "budget_tokens": _thinking_budget(self.thinking_level)}}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            resp = requests.post(
                _append_path(self.base_url, "/chat/completions"),
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            if resp.status_code >= 400:
                raise AssistantLLMError(_http_error_message(resp, self.api_key))
            try:
                data = resp.json()
            except ValueError as e:
                raise AssistantLLMError(f"模型返回了非 JSON 响应：{_sanitize_error(resp.text[:300], self.api_key)}") from e
            choices = data.get("choices") or []
            if not choices:
                raise AssistantLLMError("模型没有返回 choices，请检查模型 ID 或服务兼容性。")
            message = choices[0].get("message") or {}
            if not message.get("content") and not message.get("tool_calls"):
                raise AssistantLLMError("模型返回为空，没有文字或工具调用。")
            return message
        except AssistantLLMError:
            raise
        except requests.Timeout as e:
            raise AssistantLLMError(f"模型调用超时（{self.timeout_seconds}s），请稍后重试或调大 Assistant 超时。") from e
        except requests.ConnectionError as e:
            raise AssistantLLMError(f"连接模型服务失败：{_sanitize_error(e, self.api_key)}") from e
        except Exception as e:
            logger.exception("assistant openai-compatible request failed")
            raise AssistantLLMError(f"模型调用失败：{_sanitize_error(e, self.api_key)}") from e

    def _chat_anthropic(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"
        system = ""
        anthropic_messages: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                system = (system + "\n\n" + (msg.get("content") or "")).strip()
                continue
            if role == "tool":
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id") or msg.get("name") or "tool",
                    "content": msg.get("content") or "{}",
                })
                continue
            if pending_tool_results:
                anthropic_messages.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []
            if role == "assistant" and msg.get("tool_calls"):
                content: list[dict[str, Any]] = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg.get("content")})
                for call in msg.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    content.append({"type": "tool_use", "id": call.get("id") or fn.get("name") or "tool", "name": fn.get("name") or "", "input": args})
                anthropic_messages.append({"role": "assistant", "content": content})
            elif role in {"user", "assistant"}:
                anthropic_messages.append({"role": role, "content": msg.get("content") or ""})
        if pending_tool_results:
            anthropic_messages.append({"role": "user", "content": pending_tool_results})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "temperature": self.temperature,
            "max_tokens": max(1024, min(self.max_context_tokens_k * 1024 // 4, 8192)),
        }
        if self.thinking_level and self.thinking_level != "off":
            payload["thinking"] = {"type": "enabled", "budget_tokens": _thinking_budget(self.thinking_level)}
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]
        try:
            resp = requests.post(
                _append_path(self.base_url, "/messages"),
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            if resp.status_code >= 400:
                raise AssistantLLMError(_http_error_message(resp, self.api_key))
            try:
                data = resp.json()
            except ValueError as e:
                raise AssistantLLMError(f"模型返回了非 JSON 响应：{_sanitize_error(resp.text[:300], self.api_key)}") from e
            content = data.get("content") or []
            text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            tool_calls = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id") or block.get("name") or "tool",
                        "type": "function",
                        "function": {"name": block.get("name") or "", "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False)},
                    })
            out = {"role": "assistant", "content": "\n".join([p for p in text_parts if p]).strip()}
            if tool_calls:
                out["tool_calls"] = tool_calls
            if not out.get("content") and not out.get("tool_calls"):
                raise AssistantLLMError("模型返回为空，没有文字或工具调用。")
            return out
        except AssistantLLMError:
            raise
        except requests.Timeout as e:
            raise AssistantLLMError(f"模型调用超时（{self.timeout_seconds}s），请稍后重试或调大 Assistant 超时。") from e
        except requests.ConnectionError as e:
            raise AssistantLLMError(f"连接模型服务失败：{_sanitize_error(e, self.api_key)}") from e
        except Exception as e:
            logger.exception("assistant anthropic-compatible request failed")
            raise AssistantLLMError(f"模型调用失败：{_sanitize_error(e, self.api_key)}") from e


def _thinking_budget(level: str) -> int:
    return {
        "minimal": 512,
        "low": 1024,
        "medium": 2048,
        "high": 4096,
        "max": 8192,
        "xhigh": 8192,
        "auto": 2048,
    }.get((level or "").lower(), 2048)


def _sanitize_error(error: Exception | str, api_key: str = "") -> str:
    text = str(error) or getattr(error, "__class__", type(error)).__name__
    if api_key:
        text = text.replace(api_key, "***")
    return text


def _http_error_message(resp: requests.Response, api_key: str = "") -> str:
    preview = resp.text[:800]
    try:
        data = resp.json()
        detail = data.get("error") or data.get("detail") or data.get("message")
        if isinstance(detail, dict):
            preview = detail.get("message") or json.dumps(detail, ensure_ascii=False)[:800]
        elif detail:
            preview = str(detail)[:800]
    except ValueError:
        pass
    return f"模型服务返回 HTTP {resp.status_code}：{_sanitize_error(preview, api_key)}"


# Backwards-compatible alias used by older service code/tests.
OpenAICompatibleClient = AssistantLLMClient
