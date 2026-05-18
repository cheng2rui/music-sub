"""Settings API routes."""
from pathlib import Path
import yaml
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.config import CONFIG_PATH, load_config, AppConfig
import app.config as cfg_module

router = APIRouter()

MASK_SUFFIX = "••••••"
QB_PASSWORD_MASK = MASK_SUFFIX


def _mask_secret(value: str, prefix_len: int = 0) -> str:
    if not value:
        return ""
    return f"{value[:prefix_len]}{MASK_SUFFIX}" if prefix_len else MASK_SUFFIX


def _is_unchanged_mask(value: str, existing: str, prefix_len: int = 0) -> bool:
    """Return True only for the exact mask this API generated for the existing secret."""
    return bool(existing) and value == _mask_secret(existing, prefix_len)


class SiteSettingInput(BaseModel):
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    token: str = ""
    cookie: str = ""


class QBSettingInput(BaseModel):
    host: str = "http://localhost:8080"
    username: str = "admin"
    password: str = ""
    category: str = "music"
    save_path: str = "/downloads/music"
    tag: str = "music-sub"


class PathsSettingInput(BaseModel):
    library: str = "/music"
    structure: str = "{artist}/{album}"
    downloads: str = "/downloads/music"


class ScraperSettingInput(BaseModel):
    sources: list[str] = ["qqmusic", "netease", "kugou", "migu", "kuwo", "musicbrainz"]
    embed_cover: bool = True
    cover_max_size: int = 0
    save_cover_file: bool = True
    save_lyrics: bool = True
    save_lyrics_to_tag: bool = True
    save_lyrics_file: bool = True
    save_nfo: bool = False
    rename_file: bool = False
    rename_template: str = "${track} - ${title}"
    overwrite_tag: bool = False


class SchedulerSettingInput(BaseModel):
    search_interval_minutes: int = 30
    check_complete_interval_minutes: int = 5
    cleanup_scan_enabled: bool = True
    cleanup_scan_interval_hours: int = 24


class TelegramNotifyInput(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    on_download_added: bool = False
    on_download_complete: bool = True
    on_scrape_complete: bool = True
    on_error: bool = True
    on_cleanup_candidates: bool = True


class NotifySettingInput(BaseModel):
    telegram: TelegramNotifyInput = TelegramNotifyInput()


class AssistantProviderInput(BaseModel):
    provider: str = "openai_compatible"
    runtime: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: int = 60


class AssistantSettingInput(BaseModel):
    enabled: bool = False
    provider: AssistantProviderInput = AssistantProviderInput()
    max_history_messages: int = 20
    require_confirm_for_download: bool = True
    require_confirm_for_delete: bool = True
    require_confirm_for_apply_tools: bool = True
    allow_online_download: bool = False
    allow_library_write: bool = True
    allow_task_delete: bool = False
    enabled_tools: list[str] = []


class AllSettings(BaseModel):
    sites: dict[str, SiteSettingInput] = {}
    qbittorrent: QBSettingInput = QBSettingInput()
    paths: PathsSettingInput = PathsSettingInput()
    scraper: ScraperSettingInput = ScraperSettingInput()
    scheduler: SchedulerSettingInput = SchedulerSettingInput()
    notify: NotifySettingInput = NotifySettingInput()
    assistant: AssistantSettingInput = AssistantSettingInput()


@router.get("/", response_model=AllSettings)
def get_settings():
    """Get current settings (passwords masked)."""
    data = AllSettings(
        sites={name: SiteSettingInput(**s.model_dump()) for name, s in cfg_module.config.sites.items()},
        qbittorrent=QBSettingInput(**cfg_module.config.qbittorrent.model_dump()),
        paths=PathsSettingInput(**cfg_module.config.paths.model_dump()),
        scraper=ScraperSettingInput(**cfg_module.config.scraper.model_dump()),
        scheduler=SchedulerSettingInput(**cfg_module.config.scheduler.model_dump()),
        notify=NotifySettingInput(
            telegram=TelegramNotifyInput(**cfg_module.config.notify.telegram.model_dump()),
        ),
        assistant=AssistantSettingInput(**cfg_module.config.assistant.model_dump()),
    )
    # Mask sensitive fields
    for s in data.sites.values():
        if s.api_key:
            s.api_key = _mask_secret(s.api_key, 6)
        if s.cookie:
            s.cookie = _mask_secret(s.cookie, 10)
        if s.token:
            s.token = _mask_secret(s.token, 6)
    if data.qbittorrent.password:
        data.qbittorrent.password = QB_PASSWORD_MASK
    if data.notify.telegram.bot_token:
        data.notify.telegram.bot_token = _mask_secret(data.notify.telegram.bot_token, 6)
    if data.assistant.provider.api_key:
        data.assistant.provider.api_key = _mask_secret(data.assistant.provider.api_key, 6)
    return data


def _existing_device(path: str) -> int | None:
    """Return st_dev for path or its nearest existing parent."""
    try:
        p = Path(path).expanduser()
        while not p.exists() and p.parent != p:
            p = p.parent
        if p.exists():
            return p.stat().st_dev
    except Exception:
        return None
    return None


def _path_warnings(paths: PathsSettingInput) -> list[str]:
    warnings: list[str] = []
    downloads_dev = _existing_device(paths.downloads)
    library_dev = _existing_device(paths.library)
    if downloads_dev is not None and library_dev is not None and downloads_dev != library_dev:
        warnings.append(
            "下载目录和音乐库目录位于不同文件系统，无法使用硬链接；整理时会复制文件并占用额外空间。"
        )
    return warnings


@router.put("/")
def save_settings(settings: AllSettings):
    """Save settings to config.yaml and reload."""

    # Build raw dict for YAML. Keep auth even though it is managed through the
    # dedicated password API; older versions accidentally dropped auth on save.
    raw = {
        "sites": {},
        "qbittorrent": settings.qbittorrent.model_dump(),
        "paths": settings.paths.model_dump(),
        "scraper": settings.scraper.model_dump(),
        "scheduler": settings.scheduler.model_dump(),
        "notify": settings.notify.model_dump(),
        "auth": cfg_module.config.auth.model_dump(),
        "assistant": settings.assistant.model_dump(),
    }

    # For sites, merge with existing to preserve unmasked secrets
    for name, site_input in settings.sites.items():
        site_dict = site_input.model_dump()
        existing = cfg_module.config.sites.get(name)
        if existing:
            # Don't overwrite secrets only when the submitted value is the exact mask we generated.
            if _is_unchanged_mask(site_dict.get("api_key", ""), existing.api_key, 6):
                site_dict["api_key"] = existing.api_key
            if _is_unchanged_mask(site_dict.get("cookie", ""), existing.cookie, 10):
                site_dict["cookie"] = existing.cookie
            if _is_unchanged_mask(site_dict.get("token", ""), existing.token, 6):
                site_dict["token"] = existing.token
        raw["sites"][name] = site_dict

    # Preserve QB password only if the exact generated mask was submitted.
    if raw["qbittorrent"]["password"] == QB_PASSWORD_MASK and cfg_module.config.qbittorrent.password:
        raw["qbittorrent"]["password"] = cfg_module.config.qbittorrent.password

    # Preserve telegram bot_token only if the exact generated mask was submitted.
    if _is_unchanged_mask(raw["notify"]["telegram"].get("bot_token", ""), cfg_module.config.notify.telegram.bot_token, 6):
        raw["notify"]["telegram"]["bot_token"] = cfg_module.config.notify.telegram.bot_token

    # Preserve assistant api_key only if the exact generated mask was submitted.
    if _is_unchanged_mask(raw["assistant"]["provider"].get("api_key", ""), cfg_module.config.assistant.provider.api_key, 6):
        raw["assistant"]["provider"]["api_key"] = cfg_module.config.assistant.provider.api_key

    # Write YAML
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)

    # Reload config and apply runtime scheduler changes immediately.
    new_config = load_config(CONFIG_PATH)
    cfg_module.config = new_config
    from app.scheduler import apply_scheduler_config
    apply_scheduler_config()

    warnings = _path_warnings(settings.paths)
    message = "Settings saved and reloaded"
    if warnings:
        message += "；" + "；".join(warnings)
    return {"ok": True, "message": message, "warnings": warnings}


@router.post("/test_qb")
def test_qb_connection():
    """Test qBittorrent connection."""
    from app.downloader.qbittorrent import QBClient
    client = QBClient()
    ok, msg = client.test_connection()
    return {"ok": ok, "message": msg}


@router.post("/test_telegram")
def test_telegram_notify():
    """Send a test message via Telegram bot using current saved config."""
    import requests
    tg = cfg_module.config.notify.telegram
    if not tg.bot_token or not tg.chat_id:
        return {"ok": False, "message": "请先填写 bot_token 和 chat_id 并保存"}
    url = f"https://api.telegram.org/bot{tg.bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": tg.chat_id,
                "text": "🎵 Music Sub Telegram 通知渠道测试成功",
                "disable_notification": False,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            return {"ok": True, "message": "发送成功。"}
        return {"ok": False, "message": f"Telegram API 返回：{data.get('description', resp.text)}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.get("/scheduler")
def get_scheduler_status():
    """Get status of all scheduled jobs."""
    from app.scheduler import get_scheduler_status
    return get_scheduler_status()


@router.post("/scheduler/{job_id}/run")
def run_scheduler_job(job_id: str):
    """Manually trigger a scheduled job."""
    from app.scheduler import scheduler
    job = scheduler.get_job(job_id)
    if not job:
        return {"ok": False, "message": "任务不存在"}
    job.modify(next_run_time=__import__("datetime").datetime.now())
    return {"ok": True, "message": f"已触发: {job_id}"}


@router.post("/test_site/{site_name}")
def test_site_connection(site_name: str):
    """Test PT site connection by attempting a search."""
    from app.services.searcher import _get_site_instance
    site = _get_site_instance(site_name)
    if not site:
        return {"ok": False, "message": f"站点 {site_name} 未启用或未配置 URL"}
    try:
        results = site.search("test")
        return {"ok": True, "message": f"连接成功，搜索返回 {len(results)} 条结果"}
    except Exception as e:
        return {"ok": False, "message": f"连接失败: {str(e)[:200]}"}

