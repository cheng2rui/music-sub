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


def _ensure_cover_compatible(cover_data: bytes, file_path: str) -> bytes:
    """保证 cover 为容器可接受的格式：mp4/m4a 只能要 jpeg 或 png。

    该函数在检测到调用者是 mp4 容器且原图不是 jpeg/png 时，会调 PIL 转为 JPEG。
    """
    if not cover_data:
        return cover_data
    suffix = (Path(file_path).suffix or "").lower().lstrip(".")
    needs_strict = suffix in {"m4a", "mp4", "aac"}
    if not needs_strict:
        return cover_data
    head = cover_data[:12]
    is_jpeg = head[:3] == b"\xff\xd8\xff"
    is_png = head[:8] == b"\x89PNG\r\n\x1a\n"
    if is_jpeg or is_png:
        return cover_data
    try:
        import io
        from PIL import Image
        buf = io.BytesIO()
        img = Image.open(io.BytesIO(cover_data)).convert("RGB")
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"Failed to convert cover to jpeg for {file_path}: {e}")
        return b""


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


def _tag_value(file_tags, key: str):
    try:
        value = file_tags[key].value
    except Exception:
        return None
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _clean_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_int(value) -> int:
    text = _clean_str(value)
    if not text:
        return 0
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else 0


def _has_artwork(file_tags) -> bool:
    try:
        art = file_tags["artwork"].value
        return bool(art)
    except Exception:
        return False


def read_embedded_cover(file_path: str) -> Optional[bytes]:
    """Read embedded artwork bytes when present."""
    try:
        f = music_tag.load_file(file_path)
        artwork = f["artwork"].value
        if not artwork:
            return None
        first = artwork[0] if isinstance(artwork, (list, tuple)) else artwork
        if isinstance(first, bytes):
            return first
        raw = getattr(first, "raw", None)
        if raw:
            return raw
        data = getattr(first, "data", None)
        if data:
            return data
    except Exception as e:
        logger.debug(f"No embedded cover readable from {file_path}: {e}")
    return None


def read_existing_tags(file_path: str) -> dict:
    """Read existing musical tags as high-confidence scrape hints."""
    try:
        f = music_tag.load_file(file_path)
    except Exception as e:
        logger.debug(f"Cannot read existing tags {file_path}: {e}")
        return {}
    data = {
        "title": _clean_str(_tag_value(f, "title")),
        "artist": _clean_str(_tag_value(f, "artist")),
        "album": _clean_str(_tag_value(f, "album")),
        "album_artist": _clean_str(_tag_value(f, "albumartist")),
        "year": _parse_int(_tag_value(f, "year")),
        "genre": _clean_str(_tag_value(f, "genre")),
        "track_number": _parse_int(_tag_value(f, "tracknumber")),
        "disc_number": _parse_int(_tag_value(f, "discnumber")),
        "lyrics": _clean_str(_tag_value(f, "lyrics")),
        "has_artwork": _has_artwork(f),
    }
    return {k: v for k, v in data.items() if v not in ("", 0, False, None)}


_COVER_FILENAMES = ("cover.jpg", "cover.png", "folder.jpg", "front.jpg", "album.jpg")


def find_local_cover_data(directory: str | Path) -> Optional[bytes]:
    """Find existing album cover bytes in a directory before falling back to online covers."""
    base = Path(directory)
    for name in _COVER_FILENAMES:
        path = base / name
        if not path.exists() or not path.is_file():
            continue
        try:
            data = path.read_bytes()
            if len(data) > 100:
                return data
        except Exception as e:
            logger.debug(f"Cannot read local cover {path}: {e}")
    return None


_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_LIKELY_BAD_RE = re.compile(r"[\u00a0-\u00ff]{2,}")


def _garble_score(text: str) -> int:
    if not text:
        return -1
    return len(_CJK_RE.findall(text)) * 5 - len(_LIKELY_BAD_RE.findall(text)) * 4 - text.count("\ufffd") * 8


def repair_garble_hint(text: str) -> str:
    """Best-effort garble repair for matching hints only; never writes files."""
    if not text or not _LIKELY_BAD_RE.search(text) or _CJK_RE.search(text):
        return text
    best = text
    best_score = _garble_score(text)
    for src in ("latin-1", "cp1252"):
        try:
            raw = text.encode(src, errors="strict")
        except UnicodeEncodeError:
            continue
        for tgt in ("utf-8", "gbk", "gb18030", "big5"):
            try:
                fixed = raw.decode(tgt, errors="strict")
            except Exception:
                continue
            score = _garble_score(fixed)
            if fixed and fixed != text and _CJK_RE.search(fixed) and score > best_score:
                best, best_score = fixed, score
    return best


def read_sidecar_lyrics(file_path: str) -> str:
    """Read .lrc sidecar lyrics if present."""
    lrc_path = Path(file_path).with_suffix(".lrc")
    if not lrc_path.exists():
        return ""
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return lrc_path.read_text(encoding=enc).strip()
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.debug(f"Cannot read sidecar lyrics {lrc_path}: {e}")
            break
    return ""


def tag_file(file_path: str, meta: MusicMeta) -> bool:
    """Write metadata to an audio file.

    Respects config settings:
    - overwrite_tag=True: overwrite fields
    - overwrite_tag=False: fill missing fields only
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
        def should_write(key: str) -> bool:
            return bool(cfg.overwrite_tag) or not _clean_str(_tag_value(f, key))

        # Write tags. overwrite_tag=False now means fill-missing instead of skip-whole-file.
        if meta.title and should_write("title"):
            f["title"] = meta.title
        if meta.artist and should_write("artist"):
            f["artist"] = meta.artist
        if meta.album and should_write("album"):
            f["album"] = meta.album
        if meta.album_artist and should_write("albumartist"):
            f["albumartist"] = meta.album_artist
        if meta.year and should_write("year"):
            f["year"] = meta.year
        if meta.genre and should_write("genre"):
            f["genre"] = meta.genre
        if meta.track_number and should_write("tracknumber"):
            f["tracknumber"] = meta.track_number
        if meta.disc_number and should_write("discnumber"):
            f["discnumber"] = meta.disc_number

        # Embed cover art — mp4/m4a 只接受 jpeg/png，避免“mp4 artwork should be either jpeg or png”报错
        if cfg.embed_cover and meta.cover_data and (cfg.overwrite_tag or not _has_artwork(f)):
            cover = meta.cover_data
            if cfg.cover_max_size > 0:
                cover = _resize_cover(cover, cfg.cover_max_size)
            cover = _ensure_cover_compatible(cover, file_path)
            if cover:
                f["artwork"] = cover

        # Write lyrics to tag
        if cfg.save_lyrics_to_tag and meta.lyrics and should_write("lyrics"):
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
