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
    sources: list[str] = ["qqmusic", "netease", "musicbrainz"]
    embed_cover: bool = True
    cover_max_size: int = 0  # 0=原图, >0=缩略图宽度(px)
    save_cover_file: bool = True  # 保存 cover.jpg 到专辑目录
    save_lyrics: bool = True
    save_lyrics_to_tag: bool = True  # 写入歌词到标签
    save_lyrics_file: bool = True  # 保存 .lrc 文件
    save_nfo: bool = False
    rename_file: bool = False  # 是否重命名文件
    rename_template: str = "${track} - ${title}"  # 重命名模板
    overwrite_tag: bool = False  # 是否覆盖已有标签


class SchedulerConfig(BaseModel):
    search_interval_minutes: int = 30
    check_complete_interval_minutes: int = 5


class TelegramNotifyConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    # 事件开关
    on_download_added: bool = False
    on_download_complete: bool = True
    on_scrape_complete: bool = True
    on_error: bool = True


class NotifyConfig(BaseModel):
    telegram: TelegramNotifyConfig = TelegramNotifyConfig()


class AuthConfig(BaseModel):
    username: str = "888"
    # Default password "888" sha256 hash
    password_hash: str = "5e968ce47ce4a17e3823c29332a39d049a8d0afb08d157eb6224625f92671a51"


class AppConfig(BaseModel):
    sites: dict[str, SiteConfig] = {}
    qbittorrent: QBConfig = QBConfig()
    paths: PathsConfig = PathsConfig()
    scraper: ScraperConfig = ScraperConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    notify: NotifyConfig = NotifyConfig()
    auth: AuthConfig = AuthConfig()


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
