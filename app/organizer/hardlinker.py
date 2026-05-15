"""Hardlink organizer - link downloaded files to library structure."""
import os
import logging
from pathlib import Path
from app.config import config
from app.organizer.naming import build_library_path

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".flac", ".mp3", ".ape", ".wav", ".aac", ".ogg", ".wma", ".m4a", ".dsf", ".dff"}


def is_audio_file(path: str) -> bool:
    """Check if file is an audio file."""
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


def get_audio_files(path: str) -> list[str]:
    """Find audio files from a file or recursively from a directory."""
    if os.path.isfile(path):
        return [path] if is_audio_file(path) else []

    files = []
    for root, _, filenames in os.walk(path):
        for f in filenames:
            full_path = os.path.join(root, f)
            if is_audio_file(full_path):
                files.append(full_path)
    return sorted(files)


def hardlink_to_library(source_dir: str, artist: str = "", album: str = "") -> list[str]:
    """Hardlink audio files from source to library directory.

    Args:
        source_dir: Directory containing downloaded files
        artist: Artist name (if known from scraping)
        album: Album name (if known from scraping)

    Returns:
        List of linked file paths in library
    """
    library_base = config.paths.library
    structure = config.paths.structure

    source_path = Path(source_dir)
    source_label = source_path.stem if source_path.is_file() else source_path.name

    # If artist/album not provided, try to infer from directory/file name
    if not artist:
        artist = source_label
    if not album:
        album = source_label

    rel_path = build_library_path(artist, album, structure)
    target_dir = os.path.join(library_base, rel_path)
    os.makedirs(target_dir, exist_ok=True)

    audio_files = get_audio_files(source_dir)
    linked = []

    for src_file in audio_files:
        filename = os.path.basename(src_file)
        target_file = os.path.join(target_dir, filename)

        if os.path.exists(target_file):
            # Already linked or exists
            linked.append(target_file)
            continue

        try:
            os.link(src_file, target_file)
            linked.append(target_file)
            logger.info(f"Hardlinked: {src_file} -> {target_file}")
        except OSError as e:
            if e.errno == 18:  # Cross-device link
                logger.warning(f"Cross-device link not supported, copying: {src_file}")
                import shutil
                shutil.copy2(src_file, target_file)
                linked.append(target_file)
            else:
                logger.error(f"Failed to hardlink {src_file}: {e}")

    # Also link cover images when source is a directory
    if os.path.isdir(source_dir):
        for root, _, filenames in os.walk(source_dir):
            for f in filenames:
                if f.lower() in ("cover.jpg", "cover.png", "folder.jpg", "front.jpg", "album.jpg"):
                    src = os.path.join(root, f)
                    dst = os.path.join(target_dir, f)
                    if not os.path.exists(dst):
                        try:
                            os.link(src, dst)
                        except OSError:
                            import shutil
                            shutil.copy2(src, dst)

    logger.info(f"Organized {len(linked)} files to {target_dir}")
    return linked
