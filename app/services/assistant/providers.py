"""Assistant LLM provider catalog."""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    base_url: str
    runtime: str = "openai_compatible"


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    runtime: str
    default_base_url: str
    default_model: str = ""
    api_key_label: str = "API Key"
    hint: str = ""
    presets: tuple[ProviderPreset, ...] = ()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["presets"] = [asdict(p) for p in self.presets]
        return data


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="openai_compatible",
        name="OpenAI 兼容",
        runtime="openai_compatible",
        default_base_url="",
        hint="通用 OpenAI-compatible 入口，手动填写 Base URL。",
    ),
    ProviderSpec(
        id="openai",
        name="OpenAI",
        runtime="openai_compatible",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        hint="OpenAI 官方 API。",
    ),
    ProviderSpec(
        id="anthropic",
        name="Anthropic Claude",
        runtime="anthropic_compatible",
        default_base_url="https://api.anthropic.com/v1",
        default_model="claude-3-5-haiku-latest",
        hint="Anthropic 官方 Messages API。",
    ),
    ProviderSpec(
        id="google",
        name="Google Gemini",
        runtime="openai_compatible",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.5-flash",
        hint="Google AI Studio 的 OpenAI-compatible 端点。",
    ),
    ProviderSpec(
        id="deepseek",
        name="DeepSeek",
        runtime="openai_compatible",
        default_base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        hint="DeepSeek 官方 OpenAI-compatible 接口。",
    ),
    ProviderSpec(
        id="minimax",
        name="MiniMax",
        runtime="anthropic_compatible",
        default_base_url="https://api.minimaxi.com/anthropic/v1",
        default_model="MiniMax-M2.7",
        hint="MiniMax Anthropic-compatible 接口。国内站用 minimaxi.com，国际站用 minimax.io。",
        presets=(
            ProviderPreset("minimax-cn", "中国内地", "https://api.minimaxi.com/anthropic/v1", "anthropic_compatible"),
            ProviderPreset("minimax-global", "国际站", "https://api.minimax.io/anthropic/v1", "anthropic_compatible"),
        ),
    ),
    ProviderSpec(
        id="xiaomi",
        name="小米 Mimo",
        runtime="openai_compatible",
        default_base_url="https://api.xiaomimimo.com/v1",
        hint="小米 Mimo OpenAI-compatible 接口。",
        presets=(
            ProviderPreset("xiaomi-standard", "标准端点", "https://api.xiaomimimo.com/v1"),
            ProviderPreset("xiaomi-cn", "Token Plan / 中国", "https://token-plan-cn.xiaomimimo.com/v1"),
            ProviderPreset("xiaomi-sgp", "Token Plan / 新加坡", "https://token-plan-sgp.xiaomimimo.com/v1"),
            ProviderPreset("xiaomi-ams", "Token Plan / 欧洲", "https://token-plan-ams.xiaomimimo.com/v1"),
        ),
    ),
    ProviderSpec(
        id="zhipu",
        name="智谱 GLM",
        runtime="openai_compatible",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4.5-flash",
        hint="智谱开放平台 OpenAI-compatible 接口。",
        presets=(
            ProviderPreset("zhipu-general", "通用 API", "https://open.bigmodel.cn/api/paas/v4"),
            ProviderPreset("zhipu-coding", "Coding Plan", "https://open.bigmodel.cn/api/coding/paas/v4"),
        ),
    ),
    ProviderSpec(
        id="siliconflow",
        name="硅基流动",
        runtime="openai_compatible",
        default_base_url="https://api.siliconflow.cn/v1",
        hint="SiliconFlow OpenAI-compatible 接口。",
        presets=(
            ProviderPreset("siliconflow-cn", "中国大陆", "https://api.siliconflow.cn/v1"),
            ProviderPreset("siliconflow-global", "Global", "https://api.siliconflow.com/v1"),
        ),
    ),
    ProviderSpec(
        id="alibaba",
        name="阿里云百炼",
        runtime="openai_compatible",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        hint="DashScope / 阿里云百炼 OpenAI-compatible 接口。",
        presets=(
            ProviderPreset("alibaba-cn", "中国内地", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ProviderPreset("alibaba-global", "国际站", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            ProviderPreset("alibaba-cn-coding", "中国内地 / Coding Plan", "https://coding.dashscope.aliyuncs.com/v1"),
            ProviderPreset("alibaba-global-coding", "国际站 / Coding Plan", "https://coding-intl.dashscope.aliyuncs.com/v1"),
        ),
    ),
    ProviderSpec(
        id="baidu_qianfan",
        name="百度千帆",
        runtime="openai_compatible",
        default_base_url="https://qianfan.baidubce.com/v2",
        hint="百度千帆 OpenAI-compatible V2 接口。",
        presets=(
            ProviderPreset("baidu-general", "通用 API", "https://qianfan.baidubce.com/v2"),
            ProviderPreset("baidu-coding", "Coding Plan", "https://qianfan.baidubce.com/v2/coding"),
        ),
    ),
    ProviderSpec(
        id="moonshot",
        name="Moonshot / Kimi",
        runtime="openai_compatible",
        default_base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2-0711-preview",
        hint="Moonshot / Kimi OpenAI-compatible 接口。",
        presets=(
            ProviderPreset("moonshot-cn", "中国站", "https://api.moonshot.cn/v1"),
            ProviderPreset("moonshot-global", "国际站", "https://api.moonshot.ai/v1"),
            ProviderPreset("kimi-coding", "Kimi for Coding", "https://api.kimi.com/coding/v1", "anthropic_compatible"),
        ),
    ),
    ProviderSpec(
        id="openrouter",
        name="OpenRouter",
        runtime="openai_compatible",
        default_base_url="https://openrouter.ai/api/v1",
        hint="OpenRouter 聚合模型平台。",
    ),
)


def list_providers() -> list[dict]:
    return [p.to_dict() for p in PROVIDERS]


def get_provider(provider_id: str) -> ProviderSpec | None:
    provider_id = (provider_id or "").strip()
    return next((p for p in PROVIDERS if p.id == provider_id), None)


def resolve_provider(provider_id: str, base_url: str = "") -> tuple[str, str]:
    spec = get_provider(provider_id)
    if not spec:
        return "openai_compatible", base_url
    return spec.runtime, base_url or spec.default_base_url
