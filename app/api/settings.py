"""Settings API routes."""
import yaml
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.config import config, CONFIG_PATH, load_config, AppConfig

router = APIRouter()


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
    sources: list[str] = ["qqmusic", "netease", "musicbrainz"]
    embed_cover: bool = True
    save_lyrics: bool = True
    save_nfo: bool = False


class SchedulerSettingInput(BaseModel):
    search_interval_minutes: int = 30
    check_complete_interval_minutes: int = 5


class AllSettings(BaseModel):
    sites: dict[str, SiteSettingInput] = {}
    qbittorrent: QBSettingInput = QBSettingInput()
    paths: PathsSettingInput = PathsSettingInput()
    scraper: ScraperSettingInput = ScraperSettingInput()
    scheduler: SchedulerSettingInput = SchedulerSettingInput()


@router.get("/", response_model=AllSettings)
def get_settings():
    """Get current settings (passwords masked)."""
    data = AllSettings(
        sites={name: SiteSettingInput(**s.model_dump()) for name, s in config.sites.items()},
        qbittorrent=QBSettingInput(**config.qbittorrent.model_dump()),
        paths=PathsSettingInput(**config.paths.model_dump()),
        scraper=ScraperSettingInput(**config.scraper.model_dump()),
        scheduler=SchedulerSettingInput(**config.scheduler.model_dump()),
    )
    # Mask sensitive fields
    for s in data.sites.values():
        if s.api_key:
            s.api_key = s.api_key[:6] + "***"
        if s.cookie:
            s.cookie = s.cookie[:10] + "***"
        if s.token:
            s.token = s.token[:6] + "***"
    if data.qbittorrent.password:
        data.qbittorrent.password = "***"
    return data


@router.put("/")
def save_settings(settings: AllSettings):
    """Save settings to config.yaml and reload."""
    import app.config as cfg_module

    # Build raw dict for YAML
    raw = {
        "sites": {},
        "qbittorrent": settings.qbittorrent.model_dump(),
        "paths": settings.paths.model_dump(),
        "scraper": settings.scraper.model_dump(),
        "scheduler": settings.scheduler.model_dump(),
    }

    # For sites, merge with existing to preserve unmasked secrets
    for name, site_input in settings.sites.items():
        site_dict = site_input.model_dump()
        existing = config.sites.get(name)
        if existing:
            # Don't overwrite secrets if masked
            if site_dict.get("api_key", "").endswith("***"):
                site_dict["api_key"] = existing.api_key
            if site_dict.get("cookie", "").endswith("***"):
                site_dict["cookie"] = existing.cookie
            if site_dict.get("token", "").endswith("***"):
                site_dict["token"] = existing.token
        raw["sites"][name] = site_dict

    # Preserve QB password if masked
    if raw["qbittorrent"]["password"] == "***":
        raw["qbittorrent"]["password"] = config.qbittorrent.password

    # Write YAML
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)

    # Reload config
    new_config = load_config(CONFIG_PATH)
    cfg_module.config = new_config

    return {"ok": True, "message": "Settings saved and reloaded"}


@router.post("/test_qb")
def test_qb_connection():
    """Test qBittorrent connection."""
    from app.downloader.qbittorrent import QBClient
    client = QBClient()
    ok, msg = client.test_connection()
    return {"ok": ok, "message": msg}
