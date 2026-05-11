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
    save_lyrics: bool = True
    save_nfo: bool = False


class SchedulerConfig(BaseModel):
    search_interval_minutes: int = 30
    check_complete_interval_minutes: int = 5


class AppConfig(BaseModel):
    sites: dict[str, SiteConfig] = {}
    qbittorrent: QBConfig = QBConfig()
    paths: PathsConfig = PathsConfig()
    scraper: ScraperConfig = ScraperConfig()
    scheduler: SchedulerConfig = SchedulerConfig()


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
