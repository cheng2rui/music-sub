"""Music file tagger - write metadata to audio files.

Inspired by music-tag-web's update_ids.py:
- Variable template support (${title}, ${artist}, ${album}, ${track}, ${filename})
- Cover embedding with optional resize
- Lyrics to tag + .lrc file
- File renaming by template
"""
import os
import re
import logging
from pathlib import Path
from typing import Optional
import music_tag
from app.scrapers.base import MusicMeta
from app.config import config

logger = logging.getLogger(__name__)

# Template variable pattern: ${xxx}
TEMPLATE_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_template(template: str, variables: dict) -> str:
    """Resolve ${var} placeholders in template string."""
    def replacer(match):
        key = match.group(1)
        return str(variables.get(key, ""))
    result = TEMPLATE_PATTERN.sub(replacer, template)
    # Clean up invalid filename chars
    result = re.sub(r'[<>:"/\\|?*]', "", result)
    return result.strip()


def _resize_cover(cover_data: bytes, max_size: int) -> bytes:
    """Resize cover image to max_size width, keeping aspect ratio."""
    if not cover_data or max_size <= 0:
        return cover_data
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(cover_data))
        if img.width <= max_size:
            return cover_data
        ratio = max_size / img.width
        new_size = (max_size, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "JPEG" if img.mode == "RGB" else "PNG"
        img.save(buf, format=fmt, quality=90)
        return buf.getvalue()
    except ImportError:
        logger.warning("Pillow not installed, skipping cover resize")
        return cover_data
    except Exception as e:
        logger.warning(f"Cover resize failed: {e}")
        return cover_data


def read_audio_metadata(file_path: str) -> dict:
    """Read stable technical metadata from an audio file for DB caching."""
    try:
        import mutagen
        audio = mutagen.File(file_path)
        if not audio or not getattr(audio, "info", None):
            return {}
        info = audio.info
        duration = getattr(info, "length", None)
        return {
            "duration": round(float(duration), 1) if duration else None,
            "bitrate": int(getattr(info, "bitrate", 0) or 0) or None,
            "sample_rate": int(getattr(info, "sample_rate", 0) or 0) or None,
            "channels": int(getattr(info, "channels", 0) or 0) or None,
        }
    except Exception as e:
        logger.warning(f"Failed to read audio metadata {file_path}: {e}")
        return {}


def tag_file(file_path: str, meta: MusicMeta) -> bool:
    """Write metadata to an audio file.

    Respects config settings:
    - overwrite_tag: skip if file already has tags
    - embed_cover + cover_max_size
    - save_lyrics_to_tag
    - rename_file + rename_template
    """
    cfg = config.scraper
    try:
        f = music_tag.load_file(file_path)
    except Exception as e:
        logger.error(f"Cannot load file {file_path}: {e}")
        return False

    try:
        # Check if we should skip (already tagged and overwrite disabled)
        if not cfg.overwrite_tag:
            existing_title = f["title"].value
            existing_artist = f["artist"].value
            if existing_title and existing_artist:
                logger.debug(f"Skipping already tagged: {file_path}")
                return True

        # Write tags
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
        if cfg.embed_cover and meta.cover_data:
            cover = meta.cover_data
            if cfg.cover_max_size > 0:
                cover = _resize_cover(cover, cfg.cover_max_size)
            f["artwork"] = cover

        # Write lyrics to tag
        if cfg.save_lyrics_to_tag and meta.lyrics:
            f["lyrics"] = meta.lyrics

        f.save()
        logger.info(f"Tagged: {file_path} -> {meta.artist} - {meta.title}")

        # Rename file if configured
        if cfg.rename_file and cfg.rename_template:
            _rename_file(file_path, meta)

        return True
    except Exception as e:
        logger.error(f"Failed to tag {file_path}: {e}")
        return False


def _rename_file(file_path: str, meta: MusicMeta):
    """Rename file using template variables."""
    cfg = config.scraper
    p = Path(file_path)
    variables = {
        "title": meta.title or "",
        "artist": meta.artist or "",
        "album": meta.album or "",
        "track": str(meta.track_number).zfill(2) if meta.track_number else "00",
        "filename": p.stem,
    }
    new_name = _resolve_template(cfg.rename_template, variables)
    if not new_name:
        return
    new_path = p.parent / f"{new_name}{p.suffix}"
    if new_path == p or new_path.exists():
        return
    try:
        os.rename(file_path, str(new_path))
        logger.info(f"Renamed: {p.name} -> {new_path.name}")
    except Exception as e:
        logger.error(f"Rename failed: {e}")


def save_lyrics(file_path: str, lyrics: str) -> bool:
    """Save lyrics as .lrc file next to the audio file."""
    cfg = config.scraper
    if not lyrics or not cfg.save_lyrics_file:
        return False
    lrc_path = Path(file_path).with_suffix(".lrc")
    if lrc_path.exists() and not cfg.overwrite_tag:
        return True
    try:
        lrc_path.write_text(lyrics, encoding="utf-8")
        logger.info(f"Saved lyrics: {lrc_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save lyrics: {e}")
        return False


def save_cover(directory: str, cover_data: bytes) -> bool:
    """Save cover.jpg in the album directory."""
    cfg = config.scraper
    if not cover_data or not cfg.save_cover_file:
        return False
    cover_path = os.path.join(directory, "cover.jpg")
    if os.path.exists(cover_path) and not cfg.overwrite_tag:
        return True
    # Resize if configured
    if cfg.cover_max_size > 0:
        cover_data = _resize_cover(cover_data, cfg.cover_max_size)
    try:
        with open(cover_path, "wb") as f:
            f.write(cover_data)
        logger.info(f"Saved cover: {cover_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save cover: {e}")
        return False


def _xml_escape(s: str) -> str:
    """Escape XML special characters."""
    if not s:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def save_album_nfo(directory: str, meta: MusicMeta, tracks: list = None) -> bool:
    """Save album.nfo (Kodi/Jellyfin compatible) in album directory.

    Schema reference: https://kodi.wiki/view/NFO_files/Music
    """
    cfg = config.scraper
    if not cfg.save_nfo:
        return False
    nfo_path = os.path.join(directory, "album.nfo")
    if os.path.exists(nfo_path) and not cfg.overwrite_tag:
        return True
    try:
        lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', "<album>"]
        lines.append(f"  <title>{_xml_escape(meta.album)}</title>")
        if meta.album_artist or meta.artist:
            lines.append(f"  <artist>{_xml_escape(meta.album_artist or meta.artist)}</artist>")
            lines.append(f"  <albumartist>{_xml_escape(meta.album_artist or meta.artist)}</albumartist>")
        if meta.year:
            lines.append(f"  <year>{meta.year}</year>")
        if meta.genre:
            lines.append(f"  <genre>{_xml_escape(meta.genre)}</genre>")
        if meta.source:
            lines.append(f"  <source>{_xml_escape(meta.source)}</source>")
        for t in tracks or []:
            lines.append("  <track>")
            if t.get("track_number"):
                lines.append(f"    <position>{t['track_number']}</position>")
            lines.append(f"    <title>{_xml_escape(t.get('title', ''))}</title>")
            if t.get("duration"):
                lines.append(f"    <duration>{t['duration']}</duration>")
            lines.append("  </track>")
        lines.append("</album>")
        with open(nfo_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info(f"Saved NFO: {nfo_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save NFO: {e}")
        return False
