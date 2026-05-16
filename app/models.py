"""ORM models."""
import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float
from app.db import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(String(255), nullable=False)
    type = Column(String(50), default="artist")  # artist/album/keyword
    quality = Column(String(50), default="any")  # flac/mp3/any
    sites = Column(String(255), default="all")
    enabled = Column(Boolean, default=True)
    last_search_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DownloadTask(Base):
    __tablename__ = "download_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, nullable=True)
    torrent_name = Column(String(500), nullable=False)
    torrent_hash = Column(String(64), nullable=True)
    site = Column(String(50), nullable=False)
    size = Column(Float, default=0)
    status = Column(String(50), default="downloading")
    save_path = Column(String(500), nullable=True)
    link_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class MusicFile(Base):
    __tablename__ = "music_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=True)
    file_path = Column(String(1000), nullable=False)
    link_path = Column(String(1000), nullable=True)
    artist = Column(String(255), nullable=True)
    album = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)
    year = Column(Integer, nullable=True)
    genre = Column(String(100), nullable=True)
    track_number = Column(Integer, nullable=True)
    disc_number = Column(Integer, nullable=True)
    duration = Column(Float, nullable=True)
    bitrate = Column(Integer, nullable=True)
    sample_rate = Column(Integer, nullable=True)
    channels = Column(Integer, nullable=True)
    format = Column(String(20), nullable=True)
    scraped = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
