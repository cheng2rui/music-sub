"""Pydantic schemas for API."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class SubscriptionCreate(BaseModel):
    keyword: str
    type: str = "artist"
    quality: str = "any"
    sites: str | list[str] = "all"


class SubscriptionUpdate(BaseModel):
    keyword: str | None = None
    type: str | None = None
    quality: str | None = None
    sites: str | list[str] | None = None
    enabled: bool | None = None


class SubscriptionResponse(BaseModel):
    id: int
    keyword: str
    type: str
    quality: str
    sites: str
    enabled: bool
    last_search_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TorrentResult(BaseModel):
    site: str
    title: str
    torrent_id: str
    size: float = 0
    seeders: int = 0
    leechers: int = 0
    upload_time: Optional[str] = None
    free: bool = False


class DownloadTaskResponse(BaseModel):
    id: int
    torrent_name: str
    site: str
    status: str
    size: float
    created_at: datetime
    completed_at: Optional[datetime] = None
    torrent_hash: Optional[str] = None
    qb_state: Optional[str] = None
    progress: Optional[float] = None
    qb_missing: bool = False
    download_speed: Optional[float] = None
    upload_speed: Optional[float] = None
    eta: Optional[int] = None
    amount_left: Optional[float] = None
    external_qb: bool = False
    content_path: Optional[str] = None
    save_path: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    keyword: str
    sites: list[str] = []
