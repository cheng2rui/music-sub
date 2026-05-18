"""ORM models."""
import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text
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


class AssistantConversation(Base):
    __tablename__ = "assistant_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), default="新对话")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, nullable=False)
    role = Column(String(50), nullable=False)  # user / assistant / tool / system
    content = Column(Text, default="")
    tool_name = Column(String(100), nullable=True)
    tool_call_id = Column(String(100), nullable=True)
    tool_args_json = Column(Text, nullable=True)
    tool_result_json = Column(Text, nullable=True)
    status = Column(String(50), default="done")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AssistantAction(Base):
    __tablename__ = "assistant_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(String(64), unique=True, nullable=False)
    conversation_id = Column(Integer, nullable=False)
    tool_name = Column(String(100), nullable=False)
    tool_args_json = Column(Text, default="{}")
    result_json = Column(Text, nullable=True)
    risk = Column(String(50), default="low")
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class MusicFile(Base):
    __tablename__ = "music_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=True)
    file_path = Column(String(1000), nullable=False)
    link_path = Column(String(1000), nullable=True)
    artist = Column(String(255), nullable=True)
    album_artist = Column(String(255), nullable=True)
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
