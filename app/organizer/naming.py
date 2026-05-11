"""Naming rules for music file organization."""
import re
import unicodedata


def sanitize_filename(name: str) -> str:
    """Remove invalid filesystem characters."""
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = name.strip(". ")
    return name or "Unknown"


def build_library_path(artist: str, album: str, structure: str = "{artist}/{album}") -> str:
    """Build relative path from artist/album using structure template."""
    artist = sanitize_filename(artist or "Unknown Artist")
    album = sanitize_filename(album or "Unknown Album")
    return structure.format(artist=artist, album=album)
