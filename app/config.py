"""Configuration loader."""
import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel

CONFIG_PATH = os.environ.get("MUSIC_SUB_CONFIG", "config/config.yaml")
BASE_DIR = Path(__file__).parent.parent


class SiteConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    token: str = ""
    cookie: str = ""


class QBConfig(BaseModel):
    host: str = "http://localhost:8080"
    username: str = "admin"
    password: str = ""
    category: str = "music"
    save_path: str = "/downloads/music"
    tag: str = "music-sub"


class PathsConfig(BaseModel):
    library: str = "/music"
    structure: str = "{artist}/{album}"
    downloads: str = "/downloads/music"


class ScraperConfig(BaseModel):
    sources: list[str] = ["qqmusic", "netease", "kugou", "migu", "kuwo", "musicbrainz"]
    embed_cover: bool = True
    cover_max_size: int = 0  # 0=原图, >0=缩略图宽度(px)
    save_cover_file: bool = True  # 保存 cover.jpg 到专辑目录
    save_lyrics: bool = True
    save_lyrics_to_tag: bool = True  # 写入歌词到标签
    save_lyrics_file: bool = True  # 保存 .lrc 文件
    save_nfo: bool = False
    rename_file: bool = False  # 是否重命名文件
    rename_template: str = "${track} - ${title}"  # 重命名模板
    tag_write_mode: str = "fill_missing"  # skip_existing | fill_missing | overwrite
    overwrite_tag: bool = False  # 兼容旧配置；True 等价于 tag_write_mode=overwrite
    break_hardlink_before_tag: bool = True  # 写标签/sidecar 前断开硬链接，避免破坏 PT 做种文件


class SchedulerConfig(BaseModel):
    search_interval_minutes: int = 30
    check_complete_interval_minutes: int = 5
    cleanup_scan_enabled: bool = True
    cleanup_scan_interval_hours: int = 24


class NotifyChannelEvents(BaseModel):
    enabled: bool = False
    on_download_added: bool = False
    on_download_complete: bool = True
    on_scrape_complete: bool = True
    on_error: bool = True
    on_cleanup_candidates: bool = True
    assistant_chat: bool = True


class TelegramNotifyConfig(NotifyChannelEvents):
    bot_token: str = ""
    chat_id: str = ""


class WeComNotifyConfig(NotifyChannelEvents):
    corp_id: str = ""
    agent_id: str = ""
    app_secret: str = ""
    to_user: str = "@all"
    token: str = ""
    encoding_aes_key: str = ""
    proxy: str = "https://qyapi.weixin.qq.com"


class QQBotNotifyConfig(NotifyChannelEvents):
    app_id: str = ""
    app_secret: str = ""
    user_openid: str = ""
    group_openid: str = ""


class WeChatBotNotifyConfig(NotifyChannelEvents):
    webhook_url: str = ""
    token: str = ""


class NotifyConfig(BaseModel):
    webhook_token: str = ""
    telegram: TelegramNotifyConfig = TelegramNotifyConfig()
    wecom: WeComNotifyConfig = WeComNotifyConfig()
    qqbot: QQBotNotifyConfig = QQBotNotifyConfig()
    wechatbot: WeChatBotNotifyConfig = WeChatBotNotifyConfig()


class AuthConfig(BaseModel):
    username: str = "888"
    # Default password "888" sha256 hash
    password_hash: str = "5e968ce47ce4a17e3823c29332a39d049a8d0afb08d157eb6224625f92671a51"


class AssistantProviderConfig(BaseModel):
    provider: str = "openai_compatible"
    runtime: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: int = 60


class AssistantConfig(BaseModel):
    enabled: bool = False
    provider: AssistantProviderConfig = AssistantProviderConfig()
    max_history_messages: int = 20
    require_confirm_for_download: bool = True
    require_confirm_for_delete: bool = True
    require_confirm_for_apply_tools: bool = True
    allow_online_download: bool = False
    allow_library_write: bool = True
    allow_task_delete: bool = False
    enabled_tools: list[str] = []  # empty means all registered tools are enabled


class AppConfig(BaseModel):
    sites: dict[str, SiteConfig] = {}
    qbittorrent: QBConfig = QBConfig()
    paths: PathsConfig = PathsConfig()
    scraper: ScraperConfig = ScraperConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    notify: NotifyConfig = NotifyConfig()
    auth: AuthConfig = AuthConfig()
    assistant: AssistantConfig = AssistantConfig()


def load_config(path: str = None) -> AppConfig:
    """Load config from YAML file."""
    config_path = path or CONFIG_PATH
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    sites = {}
    for name, site_data in data.get("sites", {}).items():
        sites[name] = SiteConfig(**(site_data or {}))
    data["sites"] = sites
    return AppConfig(**data)


config = load_config()
