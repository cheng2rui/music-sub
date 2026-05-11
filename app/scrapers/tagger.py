"""Music file tagger - write metadata to audio files."""
import os
import logging
from pathlib import Path
from typing import Optional
import music_tag
from app.scrapers.base import MusicMeta
from app.config import config

logger = logging.getLogger(__name__)


def tag_file(file_path: str, meta: MusicMeta) -> bool:
    """Write metadata to an audio file using music_tag.

    Args:
        file_path: Path to audio file
        meta: Metadata to write

    Returns:
        True if successful
    """
    try:
        f = music_tag.load_file(file_path)
    except Exception as e:
        logger.error(f"Cannot load file {file_path}: {e}")
        return False

    try:
        if meta.title:
            f["title"] = meta.title
        if meta.artist:
            f["artist"] = meta.artist
        if meta.album:
            f["album"] = meta.album
        if meta.album_artist:
            f["albumartist"] = meta.album_artist
        if meta.year:
            f["year"] = meta.year
        if meta.genre:
            f["genre"] = meta.genre
        if meta.track_number:
            f["tracknumber"] = meta.track_number
        if meta.disc_number:
            f["discnumber"] = meta.disc_number

        # Embed cover art
        if config.scraper.embed_cover and meta.cover_data:
            f["artwork"] = meta.cover_data

        f.save()
        logger.info(f"Tagged: {file_path} -> {meta.artist} - {meta.title}")
        return True
    except Exception as e:
        logger.error(f"Failed to tag {file_path}: {e}")
        return False


def save_lyrics(file_path: str, lyrics: str) -> bool:
    """Save lyrics as .lrc file next to the audio file."""
    if not lyrics or not config.scraper.save_lyrics:
        return False
    lrc_path = Path(file_path).with_suffix(".lrc")
    try:
        lrc_path.write_text(lyrics, encoding="utf-8")
        logger.info(f"Saved lyrics: {lrc_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save lyrics: {e}")
        return False


def save_cover(directory: str, cover_data: bytes) -> bool:
    """Save cover.jpg in the album directory."""
    if not cover_data:
        return False
    cover_path = os.path.join(directory, "cover.jpg")
    if os.path.exists(cover_path):
        return True
    try:
        with open(cover_path, "wb") as f:
            f.write(cover_data)
        logger.info(f"Saved cover: {cover_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save cover: {e}")
        return False
