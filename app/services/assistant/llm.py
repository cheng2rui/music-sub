"""OpenAI-compatible LLM client for the Music Sub assistant."""
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class AssistantLLMError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.2, timeout_seconds: int = 60):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise AssistantLLMError("智能助手还没有配置模型，请先在设置里填写 Assistant 模型配置。")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                raise AssistantLLMError("模型没有返回内容。")
            return choices[0].get("message") or {}
        except AssistantLLMError:
            raise
        except Exception as e:
            logger.exception("assistant llm request failed")
            raise AssistantLLMError(f"模型调用失败：{e}") from e
