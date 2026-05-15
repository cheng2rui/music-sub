"""Pipeline: download complete → hardlink → scrape."""
import os
import datetime
import logging
from pathlib import Path
from app.config import config
from app.db import SessionLocal
from app.models import DownloadTask, MusicFile
from app.downloader.monitor import get_newly_completed, mark_processed
from app.organizer.hardlinker import hardlink_to_library, get_audio_files, is_audio_file
from app.scrapers.tagger import tag_file, save_lyrics, save_cover, save_album_nfo
from app.scrapers.base import MusicMeta
from app.services.notify import notify_download_complete, notify_scrape_complete, notify_error

logger = logging.getLogger(__name__)


def _get_scraper_chain():
    """Get ordered list of scrapers based on config."""
    scrapers = []
    for source in config.scraper.sources:
        if source == "qqmusic":
            from app.scrapers.qqmusic import QQMusicScraper
            scrapers.append(QQMusicScraper())
        elif source == "netease":
            from app.scrapers.netease import NetEaseScraper
            scrapers.append(NetEaseScraper())
        elif source == "kugou":
            from app.scrapers.kugou import KugouScraper
            scrapers.append(KugouScraper())
        elif source == "migu":
            from app.scrapers.migu import MiguScraper
            scrapers.append(MiguScraper())
        elif source == "musicbrainz":
            from app.scrapers.musicbrainz import MusicBrainzScraper
            scrapers.append(MusicBrainzScraper())
    return scrapers


def _scrape_file(file_path: str) -> MusicMeta | None:
    """Try to scrape metadata for a single file."""
    filename = Path(file_path).stem
    # Try to extract artist - title from filename
    parts = filename.split(" - ", 1)
    if len(parts) == 2:
        artist_hint, title_hint = parts[0].strip(), parts[1].strip()
    else:
        artist_hint, title_hint = "", filename

    scrapers = _get_scraper_chain()
    for scraper in scrapers:
        try:
            results = scraper.search(title_hint, artist_hint)
            if results:
                meta = results[0]
                # Try to get cover and lyrics
                if meta.cover_url and not meta.cover_data:
                    meta.cover_data = scraper.get_cover(meta.cover_url)
                if meta.song_id and not meta.lyrics:
                    meta.lyrics = scraper.get_lyrics(meta.song_id)
                return meta
        except Exception as e:
            logger.warning(f"[{scraper.name}] Scrape failed for {filename}: {e}")
            continue
    return None


def _process_completed_torrent(torrent: dict):
    """Process a single completed torrent: hardlink + scrape."""
    content_path = torrent.get("content_path", "")
    torrent_hash = torrent.get("hash", "")
    torrent_name = torrent.get("name", "")

    if not content_path or not os.path.exists(content_path):
        logger.warning(f"Content path not found: {content_path}")
        return

    logger.info(f"Processing completed torrent: {torrent_name}")

    # Step 1: inspect audio files and scrape one representative track first,
    # so the hardlink target can use real artist/album instead of raw torrent folder name.
    source_audio_files = get_audio_files(content_path)
    if not source_audio_files:
        logger.warning(f"No audio files found in {content_path}")
        mark_processed(torrent_hash)
        return

    meta_cache: dict[str, MusicMeta | None] = {}
    first_meta = _scrape_file(source_audio_files[0])
    meta_cache[os.path.basename(source_audio_files[0])] = first_meta
    organize_artist = (first_meta.album_artist or first_meta.artist) if first_meta else ""
    organize_album = first_meta.album if first_meta else ""

    # Step 2: Hardlink to library
    linked_files = hardlink_to_library(content_path, artist=organize_artist, album=organize_album)
    if not linked_files:
        logger.warning(f"No audio files linked from {content_path}")
        mark_processed(torrent_hash)
        return

    notify_download_complete(torrent_name, len(linked_files))

    # Step 3: Scrape and tag each linked file
    db = SessionLocal()
    try:
        # Update task status
        task = db.query(DownloadTask).filter(
            DownloadTask.torrent_hash == torrent_hash
        ).first()
        if task:
            task.status = "organized"
            task.link_path = str(Path(linked_files[0]).parent)
            db.commit()

        album_cover_saved = False
        album_meta_for_nfo: MusicMeta | None = None
        nfo_tracks: list[dict] = []
        for file_path in linked_files:
            if not is_audio_file(file_path):
                continue

            meta = meta_cache.get(os.path.basename(file_path))
            if os.path.basename(file_path) not in meta_cache:
                meta = _scrape_file(file_path)
                meta_cache[os.path.basename(file_path)] = meta
            if meta:
                tag_file(file_path, meta)
                if meta.lyrics:
                    save_lyrics(file_path, meta.lyrics)
                if meta.cover_data and not album_cover_saved:
                    save_cover(str(Path(file_path).parent), meta.cover_data)
                    album_cover_saved = True
                if album_meta_for_nfo is None:
                    album_meta_for_nfo = meta
                nfo_tracks.append({
                    "track_number": meta.track_number,
                    "title": meta.title,
                })

                # Record in DB
                music_file = MusicFile(
                    task_id=task.id if task else None,
                    file_path=file_path,
                    link_path=file_path,
                    artist=meta.artist,
                    album=meta.album,
                    title=meta.title,
                    year=meta.year,
                    genre=meta.genre,
                    format=Path(file_path).suffix.lstrip("."),
                    scraped=True,
                )
                db.add(music_file)
            else:
                # Record without scraping
                music_file = MusicFile(
                    task_id=task.id if task else None,
                    file_path=file_path,
                    link_path=file_path,
                    format=Path(file_path).suffix.lstrip("."),
                    scraped=False,
                )
                db.add(music_file)

        # Write album NFO if we have any scraped meta
        if album_meta_for_nfo and linked_files:
            save_album_nfo(
                str(Path(linked_files[0]).parent),
                album_meta_for_nfo,
                tracks=nfo_tracks,
            )

        if task:
            task.status = "scraped"
            task.completed_at = datetime.datetime.utcnow()
        db.commit()

        # Notify scrape complete
        scraped_count = sum(1 for t in nfo_tracks)
        total_count = sum(1 for f in linked_files if is_audio_file(f))
        notify_scrape_complete(torrent_name, scraped_count, total_count)
    finally:
        db.close()

    mark_processed(torrent_hash)
    logger.info(f"Completed processing: {torrent_name} ({len(linked_files)} files)")


def check_completed_downloads():
    """Check for newly completed downloads and process them."""
    newly_completed = get_newly_completed()
    if not newly_completed:
        return

    logger.info(f"Found {len(newly_completed)} newly completed downloads")
    for torrent in newly_completed:
        try:
            _process_completed_torrent(torrent)
        except Exception as e:
            logger.error(f"Failed to process {torrent.get('name')}: {e}")
            notify_error(f"处理种子: {torrent.get('name', '?')}", str(e))
            mark_processed(torrent.get("hash", ""))
