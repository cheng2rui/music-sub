"""Pipeline: download complete → hardlink → scrape."""
import os
import copy
import datetime
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from app.config import config
from app.db import SessionLocal
from app.models import DownloadTask, MusicFile
from app.downloader.monitor import get_newly_completed, mark_processed
from app.organizer.hardlinker import hardlink_to_library, get_audio_files, is_audio_file
from app.services.album_identity import canonical_album_artist, primary_artist
from app.scrapers.tagger import (
    tag_file,
    save_lyrics,
    save_cover,
    save_album_nfo,
    read_audio_metadata,
    read_existing_tags,
    read_sidecar_lyrics,
    find_local_cover_data,
    read_embedded_cover,
    repair_garble_hint,
)
from app.scrapers.base import MusicMeta
from app.scrapers.matcher import score_meta, text_score, normalize_text, artist_score
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
        elif source == "kuwo":
            from app.scrapers.kuwo import KuwoScraper
            scrapers.append(KuwoScraper())
        elif source == "musicbrainz":
            from app.scrapers.musicbrainz import MusicBrainzScraper
            scrapers.append(MusicBrainzScraper())
    return scrapers


_SOURCE_PRIORITY = {
    "qqmusic": 5,
    "kugou": 4,
    "netease": 3,
    "migu": 2,
    "kuwo": 1,
    "musicbrainz": 0,
}


def _source_priority(source: str) -> int:
    return _SOURCE_PRIORITY.get(source, -1)


class ScrapeContext:
    """Per-job scrape context for scraper reuse, search cache, and failure backoff."""

    def __init__(self):
        self.scrapers = _get_scraper_chain()
        self._search_cache: dict[tuple[str, str, str], list[MusicMeta]] = {}
        self._failures: dict[str, int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _clone_results(results: list[MusicMeta]) -> list[MusicMeta]:
        # Candidates are later enriched with cover/lyrics. Return copies so cached
        # search results stay small and do not leak mutation across tracks.
        return [copy.deepcopy(meta) for meta in results]

    def search(self, scraper, title_hint: str, artist_hint: str, filename: str) -> list[MusicMeta]:
        source = scraper.name
        key = (source, normalize_text(title_hint), normalize_text(artist_hint))
        with self._lock:
            if self._failures.get(source, 0) >= 3:
                logger.info(f"[{source}] skipped for {filename}: temporary scrape backoff")
                return []
            cached = self._search_cache.get(key)
            if cached is not None:
                return self._clone_results(cached)
        try:
            results = scraper.search(title_hint, artist_hint) or []
        except Exception as e:
            with self._lock:
                self._failures[source] = self._failures.get(source, 0) + 1
            logger.warning(f"[{source}] Scrape failed for {filename}: {e}")
            return []
        with self._lock:
            self._search_cache[key] = self._clone_results(results)
            if results:
                self._failures[source] = 0
        return self._clone_results(results)


def _safe_search(scraper, title_hint: str, artist_hint: str, filename: str, context: ScrapeContext | None = None) -> list:
    if context:
        return context.search(scraper, title_hint, artist_hint, filename)
    try:
        return scraper.search(title_hint, artist_hint) or []
    except Exception as e:
        logger.warning(f"[{scraper.name}] Scrape failed for {filename}: {e}")
        return []


def _search_all_scrapers(title_hint: str, artist_hint: str, filename: str, context: ScrapeContext | None = None) -> list[MusicMeta]:
    scrapers = context.scrapers if context else _get_scraper_chain()
    if not scrapers:
        return []
    out: list[MusicMeta] = []
    seen: set[tuple] = set()
    max_workers = max(1, min(len(scrapers), 6))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="album-cluster") as ex:
        futures = {ex.submit(_safe_search, scraper, title_hint, artist_hint, filename, context): scraper for scraper in scrapers}
        for fut in as_completed(futures):
            for meta in fut.result() or []:
                key = (meta.source, getattr(meta, "song_id", "") or "", meta.title, meta.artist, meta.album)
                if key in seen:
                    continue
                seen.add(key)
                out.append(meta)
    return out


def _scrape_file(file_path: str, title_hint: str = "", artist_hint: str = "",
                 album_hint: str = "", year_hint: int | str | None = None,
                 duration_hint: float | int | None = None,
                 track_hint: int | str | None = None,
                 context: ScrapeContext | None = None) -> MusicMeta | None:
    """Try to scrape metadata for a single file, with optional trusted title/artist hints."""
    title_hint = repair_garble_hint(title_hint or "")
    artist_hint = repair_garble_hint(artist_hint or "")
    album_hint = repair_garble_hint(album_hint or "")
    filename = Path(file_path).stem
    fallback_pairs: list[tuple[str, str]] = []
    # 去掉“01.” / “01 ” / “01-” 这种常见的轨号前缀，避免“01. 怪美的”被拆作 title=01
    import re as _re
    cleaned_filename = _re.sub(r"^\s*\d+\s*[.\-_)\u3001\uff0e]?\s*", "", filename).strip()
    if not title_hint:
        # Try `A - B` decomposition both ways since downloads can be either order.
        parts = cleaned_filename.split(" - ", 1)
        if len(parts) == 2:
            left, right = parts[0].strip(), parts[1].strip()
            artist_hint, title_hint = left, right
            fallback_pairs.append((right, left))  # also try title=A artist=B
            fallback_pairs.append((right, ""))    # bare title fallback
            fallback_pairs.append((left, ""))     # bare other-side fallback
        else:
            artist_hint, title_hint = artist_hint or "", cleaned_filename
            fallback_pairs.append((cleaned_filename, ""))
    fallback_pairs.append((title_hint, ""))  # always allow bare title retry

    scrapers = context.scrapers if context else _get_scraper_chain()
    scored_candidates = []
    scraper_by_name = {}
    seen_keys: set[tuple] = set()

    def _collect(t_hint: str, a_hint: str):
        if not scrapers:
            return
        # 并行调所有 scraper，缩短单次搜索延迟
        max_workers = max(1, min(len(scrapers), 6))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="scrape") as ex:
            futures = {
                ex.submit(_safe_search, scraper, t_hint, a_hint, filename, context): scraper
                for scraper in scrapers
            }
            for fut in as_completed(futures):
                scraper = futures[fut]
                scraper_by_name[scraper.name] = scraper
                results = fut.result() or []
                for meta in results:
                    key = (meta.source, getattr(meta, "song_id", "") or "", meta.title, meta.artist, meta.album)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    # 使用本次搜索的 hint 评分，以便 fallback 反转顺序后能拿到高分
                    scored_candidates.append(score_meta(
                        meta,
                        t_hint,
                        a_hint,
                        album_hint,
                        year_hint=year_hint,
                        duration_hint=duration_hint,
                        track_hint=track_hint,
                    ))

    _collect(title_hint, artist_hint)

    # If primary search yielded nothing useful, try alternate hint orderings to fix
    # "title - artist" filenames or rescrape calls with reversed DB fields.
    threshold = 0.48 if artist_hint else 0.42
    # 带 album_hint 调用时，同专辑余下主要走 title 区分，阈值可以略高点以避免跳走另一个专辑
    if album_hint:
        threshold = max(threshold, 0.5)
    if not scored_candidates or max((c.score for c in scored_candidates), default=0.0) < threshold:
        for alt_title, alt_artist in fallback_pairs:
            if not alt_title:
                continue
            if alt_title == title_hint and alt_artist == artist_hint:
                continue
            _collect(alt_title, alt_artist)
            if scored_candidates and max(c.score for c in scored_candidates) >= threshold:
                break

    scored_candidates.sort(key=lambda item: (item.score, _source_priority(item.meta.source)), reverse=True)
    if album_hint and scored_candidates:
        # 专辑 hint 来自种子名/资料库路径时，比单曲名更可信。
        # 如果存在同专辑候选，就只在这些候选里选；否则宁可进入较高阈值，避免
        # “同艺人同歌名但其他专辑/Live/精选集”把整张专辑带偏。
        album_matched = [item for item in scored_candidates if text_score(album_hint, item.meta.album) >= 0.5]
        if album_matched:
            dropped = len(scored_candidates) - len(album_matched)
            if dropped:
                logger.info(f"Album hint filtered {dropped} off-album candidates for {filename}: {album_hint}")
            scored_candidates = album_matched
    if scored_candidates:
        preview = "; ".join(
            f"{item.meta.source}:{item.meta.title}/{item.meta.artist}/{item.meta.album}={item.score:.2f}"
            for item in scored_candidates[:3]
        )
        logger.info(f"Smart scrape candidates for {filename}: {preview}")

    threshold = 0.48 if artist_hint else 0.42
    if album_hint:
        threshold = max(threshold, 0.5)
    for item in scored_candidates:
        if item.score < threshold:
            break
        meta = item.meta
        scraper = scraper_by_name.get(meta.source)
        if not scraper:
            continue
        try:
            if meta.cover_url and not meta.cover_data:
                meta.cover_data = scraper.get_cover(meta.cover_url)
            if meta.song_id and not meta.lyrics:
                meta.lyrics = scraper.get_lyrics(meta.song_id)
            logger.info(
                f"Smart scrape selected for {filename}: "
                f"{meta.source}:{meta.title}/{meta.artist}/{meta.album} score={item.score:.2f} reasons={','.join(item.reasons)}"
            )
            return meta
        except Exception as e:
            logger.warning(f"[{scraper.name}] Enrich failed for {filename}: {e}")
            continue
    return None


def _merge_hints(*hints: dict | None) -> dict:
    """Merge hints by priority. Earlier hints win over later hints."""
    merged: dict = {}
    for hint in reversed([h for h in hints if h]):
        for key, value in hint.items():
            if value not in (None, "", 0, False):
                merged[key] = repair_garble_hint(value) if isinstance(value, str) else value
    return merged


_CJK_TEXT_RE = re.compile(r"[\u4e00-\u9fff]")
_ROMAN_TEXT_RE = re.compile(r"[A-Za-z]")


def _has_cjk_text(value: str | None) -> bool:
    return bool(_CJK_TEXT_RE.search(value or ""))


def _looks_romanized(value: str | None) -> bool:
    text = value or ""
    return bool(_ROMAN_TEXT_RE.search(text)) and not _has_cjk_text(text)


def _prefer_trusted_cjk(existing: str | None, trusted: str | None, *, min_score: float = 0.55) -> str:
    """Keep trusted local/download Chinese names over romanized translated scraper names.

    Scrapers sometimes return English/romanized aliases for Chinese songs/albums.
    When the local filename/tag/torrent hint is Chinese and the scraped value is
    romanized or poorly matches it, the local Chinese text is the safer library
    identity. This prevents both wrong English song titles and split album dirs.
    """
    trusted = repair_garble_hint((trusted or "").strip())
    existing = (existing or "").strip()
    if not trusted:
        return existing
    if not existing:
        return trusted
    if _has_cjk_text(trusted) and (_looks_romanized(existing) or text_score(trusted, existing) < min_score):
        return trusted
    return existing


def _stabilize_scraped_meta(meta: MusicMeta | None, trusted_hint: dict | None, *, lock_album: bool = False, lock_album_artist: bool = False) -> MusicMeta | None:
    """Apply conservative local identity locks to scraper metadata.

    Textual identity priority:
    1. local/download/torrent hints for Chinese title/album/artist;
    2. locked album and album_artist for multi-track packages;
    3. scraper metadata for cover/lyrics/track/year enrichment.
    """
    if not meta:
        return None
    hint = trusted_hint or {}
    before = (meta.title, meta.artist, meta.album, meta.album_artist)
    meta.title = _prefer_trusted_cjk(meta.title, hint.get("title"), min_score=0.58)
    meta.artist = _prefer_trusted_cjk(meta.artist, hint.get("artist") or hint.get("album_artist"), min_score=0.62)
    album_hint = hint.get("album") or ""
    if lock_album and album_hint:
        meta.album = album_hint
    else:
        meta.album = _prefer_trusted_cjk(meta.album, album_hint, min_score=0.62)
    album_artist_hint = hint.get("album_artist") or hint.get("artist") or ""
    if lock_album_artist and album_artist_hint:
        meta.album_artist = album_artist_hint
    else:
        meta.album_artist = _prefer_trusted_cjk(meta.album_artist or meta.artist, album_artist_hint, min_score=0.62)
    after = (meta.title, meta.artist, meta.album, meta.album_artist)
    if before != after:
        logger.info(
            "Stabilized scraped metadata: "
            f"title={before[0]!r}->{after[0]!r}, artist={before[1]!r}->{after[1]!r}, "
            f"album={before[2]!r}->{after[2]!r}, album_artist={before[3]!r}->{after[3]!r}"
        )
    return meta


def _meta_from_hint(hint: dict) -> MusicMeta | None:
    """Build a fallback metadata object from trusted source/search result fields."""
    title = (hint or {}).get("title") or ""
    artist = (hint or {}).get("artist") or ""
    if not title and not artist:
        return None
    return MusicMeta(
        title=title,
        artist=artist,
        album=(hint or {}).get("album") or "",
        album_artist=(hint or {}).get("album_artist") or "",
        year=int((hint or {}).get("year") or 0),
        genre=(hint or {}).get("genre") or "",
        track_number=int((hint or {}).get("track_number") or 0),
        disc_number=int((hint or {}).get("disc_number") or 0) or 1,
        song_id=str((hint or {}).get("song_id") or ""),
        lyrics=(hint or {}).get("lyrics") or "",
        source=(hint or {}).get("source") or "local-tag",
    )


def _enrich_from_local_assets(file_path: str, meta: MusicMeta) -> MusicMeta:
    """Apply local asset priority without changing textual metadata.

    Cover priority follows the library convention used by mtw and common media
    servers: same-directory cover.* first, then embedded artwork, then scraper
    cover data that may already be attached to ``meta``. Lyrics are filled from
    sidecar .lrc only when the scraper did not provide lyrics.
    """
    if not meta.lyrics:
        meta.lyrics = read_sidecar_lyrics(file_path)

    local_cover = find_local_cover_data(Path(file_path).parent)
    if local_cover:
        meta.cover_data = local_cover
    elif not meta.cover_data:
        embedded_cover = read_embedded_cover(file_path)
        if embedded_cover:
            meta.cover_data = embedded_cover
    return meta


def _album_hint_from_existing_tags(files: list[str]) -> dict:
    """Infer album-level hints from tags across files in the same package."""
    from collections import Counter
    albums: Counter[str] = Counter()
    artists: Counter[str] = Counter()
    years: Counter[int] = Counter()
    for path in files[:80]:
        tags = read_existing_tags(path)
        if tags.get("album"):
            albums[str(tags["album"])] += 1
        if tags.get("album_artist") or tags.get("artist"):
            artists[str(tags.get("album_artist") or tags.get("artist"))] += 1
        if tags.get("year"):
            years[int(tags["year"])] += 1
    out: dict = {}
    if albums:
        album, count = albums.most_common(1)[0]
        if count >= 2 or len(files) == 1:
            out["album"] = album
    if artists:
        artist, count = artists.most_common(1)[0]
        if count >= 2 or len(files) == 1:
            out["artist"] = artist
            out["album_artist"] = artist
    if years:
        year, _count = years.most_common(1)[0]
        out["year"] = year
    return out


def _title_hint_for_file(path: str) -> dict:
    tags = read_existing_tags(path)
    if tags.get("title"):
        return tags
    import re as _re
    title = _re.sub(r"^\s*\d+\s*[.\-_）)、．]?\s*", "", Path(path).stem).strip()
    if title:
        tags["title"] = title
    return tags


def _album_cluster_hint(files: list[str], base_hint: dict | None = None, sample_size: int = 5,
                        context: ScrapeContext | None = None) -> dict:
    """Pick album/artist by clustering multi-track online candidates.

    This reduces drifting into compilation/live albums: several local track
    titles must point to the same online album before we lock album_hint.
    """
    if len(files) < 2:
        return {}
    base_hint = base_hint or {}
    sample = files[:sample_size]
    clusters: dict[tuple[str, str], dict] = {}
    for path in sample:
        hint = _merge_hints(base_hint, _title_hint_for_file(path))
        title = hint.get("title") or ""
        if not title:
            continue
        artist = hint.get("artist") or hint.get("album_artist") or base_hint.get("artist") or ""
        audio_meta = read_audio_metadata(path)
        candidates = _search_all_scrapers(title, artist, Path(path).stem, context=context)
        for meta in candidates:
            if not meta.album:
                continue
            scored = score_meta(
                meta,
                title,
                artist,
                base_hint.get("album") or "",
                year_hint=hint.get("year") or base_hint.get("year"),
                duration_hint=audio_meta.get("duration"),
                track_hint=hint.get("track_number"),
            )
            if scored.score < 0.45:
                continue
            key = (normalize_text(meta.album), normalize_text(meta.album_artist or meta.artist))
            bucket = clusters.setdefault(key, {"album": meta.album, "artist": meta.album_artist or meta.artist, "hits": 0, "score": 0.0, "sources": set()})
            bucket["hits"] += 1
            bucket["score"] += scored.score
            bucket["sources"].add(meta.source)
    if not clusters:
        return {}
    ranked = sorted(clusters.values(), key=lambda x: (x["hits"], x["score"], len(x["sources"])), reverse=True)
    best = ranked[0]
    # Require at least two agreeing tracks, or a dominant source score on tiny albums.
    if best["hits"] < 2:
        return {}
    out = {"album": best["album"], "artist": best["artist"], "album_artist": best["artist"], "source": "album-cluster"}
    logger.info(
        f"Album cluster selected: artist={out['artist']} album={out['album']} "
        f"hits={best['hits']} score={best['score']:.2f}"
    )
    return out


def _upsert_music_file(db, *, task_id: int | None, file_path: str, link_path: str | None, scraped: bool, meta: MusicMeta | None, audio_meta: dict):
    """Create or update a music_files row keyed by file_path to keep retries idempotent."""
    music_file = db.query(MusicFile).filter(MusicFile.file_path == file_path).first()
    if not music_file:
        music_file = MusicFile(file_path=file_path)
        db.add(music_file)

    music_file.task_id = task_id
    music_file.link_path = link_path or file_path
    music_file.format = Path(file_path).suffix.lstrip(".")
    music_file.scraped = scraped
    music_file.duration = audio_meta.get("duration")
    music_file.bitrate = audio_meta.get("bitrate")
    music_file.sample_rate = audio_meta.get("sample_rate")
    music_file.channels = audio_meta.get("channels")

    if meta:
        music_file.artist = meta.artist
        music_file.album_artist = meta.album_artist or meta.artist
        music_file.album = meta.album
        music_file.title = meta.title
        music_file.year = meta.year
        music_file.genre = meta.genre
        music_file.track_number = meta.track_number or None
        music_file.disc_number = meta.disc_number or None

    return music_file


def _mark_task_failed(torrent_hash: str, error: str):
    """Mark a tracked task failed without tagging qB as processed."""
    if not torrent_hash:
        return
    db = SessionLocal()
    try:
        task = db.query(DownloadTask).filter(DownloadTask.torrent_hash == torrent_hash).first()
        if task:
            task.status = "failed"
            db.commit()
    finally:
        db.close()


def _parse_torrent_hints(torrent_name: str) -> dict:
    """从 PT 种子名提取 artist/album/year hint。

    支持常见格式例如：
      `蔡依林 - 怪美的 (2018) - WEB-DL - 24bit ALAC-HHWEB`
      `蔡依林 - 什么什么 - 2017 - FLAC整轨`
      `蔡依林-Ugly Beauty 2018-FLAC`
      `Jay Chou - Children of the Sun 2026 - FLAC`
    """
    import re
    if not torrent_name:
        return {}
    name = torrent_name.strip()
    # 1. 先剀到全部质量/馆号/容器信息，贪婪匹配以去除后缀
    quality_re = re.compile(
        r"[\s_\-\(\[]+(WEB[- ]?DL|HHWEB|HiRes|HiFi|Hi-Res|HQ|FLAC|ALAC|APE|WAV|MP3|OGG|320k?|256k?|24bit|16bit|44\.?1kHz|48kHz|96kHz|192kHz|DSD\d*|\d+bit|\d+kHz|integral|整轨|分轨|整軌|分軌|CDDA|CD|EAC|Lossless|无损|無損).*$",
        re.IGNORECASE,
    )
    name = quality_re.sub("", name)
    name = name.strip(" -_\u3000()[]\u3010\u3011")
    # 2. 拽出年份（单年 1900-2099，忍受括号/连字符包裹）后从名字中清除
    year = ""
    year_match = re.search(r"\(?\s*(19\d{2}|20\d{2})\s*\)?", name)
    if year_match:
        year = year_match.group(1)
        name = (name[: year_match.start()] + name[year_match.end():]).strip(" -_\u3000()[]\u3010\u3011")
        name = re.sub(r"\s{2,}", " ", name)
        name = re.sub(r"-\s*-", "-", name)
        name = name.strip(" -_\u3000")
    # 3. 拆 artist - album（连字符两侧可能有空格）
    parts = re.split(r"\s*-\s*|\s+\u2013\s+", name, maxsplit=1)
    if len(parts) != 2:
        m = re.match(r"^([^\s\-]+)-(.+)$", name)
        if m:
            parts = [m.group(1), m.group(2)]
    if len(parts) != 2:
        return {}
    artist = parts[0].strip(" -_\u3000")
    album = parts[1].strip(" -_\u3000")
    # 4. 过滤明显是年份范围这种“Collection / 合集”型，artist 里不需要拼住年份
    artist = re.sub(r"\s*(19|20)\d{2}\s*$", "", artist).strip()
    if not artist or not album:
        return {}
    return {"artist": artist, "album": album, "year": year}


def _process_completed_torrent(torrent: dict):
    """Process a single completed torrent: hardlink + scrape."""
    content_path = torrent.get("content_path", "")
    torrent_hash = torrent.get("hash", "")
    torrent_name = torrent.get("name", "")
    metadata_hint = torrent.get("metadata") or {}
    # 如果上游没传 metadata，尝试从种子名提取 artist/album，避免刮削随机跳专辑
    if not metadata_hint.get("artist") and not metadata_hint.get("album"):
        parsed = _parse_torrent_hints(torrent_name)
        if parsed:
            metadata_hint = {**parsed, **metadata_hint}
            logger.info(
                f"Parsed torrent hints from name {torrent_name!r}: "
                f"artist={parsed.get('artist')} album={parsed.get('album')}"
            )
    should_mark_processed = torrent.get("mark_processed", True)

    if not content_path or not os.path.exists(content_path):
        logger.warning(f"Content path not found: {content_path}")
        return

    logger.info(f"Processing completed torrent: {torrent_name}")

    # Step 1: inspect audio files and scrape one representative track first,
    # so the hardlink target can use real artist/album instead of raw torrent folder name.
    source_audio_files = get_audio_files(content_path)
    if not source_audio_files:
        logger.warning(f"No audio files found in {content_path}")
        if should_mark_processed:
            mark_processed(torrent_hash)
        return

    scrape_context = ScrapeContext()
    meta_cache: dict[str, MusicMeta | None] = {}
    package_hint = _album_hint_from_existing_tags(source_audio_files)
    if package_hint:
        metadata_hint = _merge_hints(metadata_hint, package_hint)
        logger.info(
            f"Album-level local hints: artist={metadata_hint.get('artist')} "
            f"album={metadata_hint.get('album')} year={metadata_hint.get('year')}"
        )
    cluster_hint = _album_cluster_hint(source_audio_files, metadata_hint, context=scrape_context)
    if cluster_hint:
        metadata_hint = _merge_hints(cluster_hint, metadata_hint)
    first_existing_hint = read_existing_tags(source_audio_files[0])
    first_hint = _merge_hints(metadata_hint, first_existing_hint)
    first_audio_meta = read_audio_metadata(source_audio_files[0])
    first_meta = _scrape_file(
        source_audio_files[0],
        title_hint=first_hint.get("title") or "",
        artist_hint=first_hint.get("artist") or first_hint.get("album_artist") or "",
        album_hint=first_hint.get("album") or "",
        year_hint=first_hint.get("year") or metadata_hint.get("year"),
        duration_hint=first_audio_meta.get("duration"),
        track_hint=first_hint.get("track_number"),
        context=scrape_context,
    ) or _meta_from_hint(first_hint)
    if first_meta:
        # The first track decides the target album folder. Preserve trusted
        # Chinese torrent/tag/path hints here so a romanized scraper result does
        # not create a second English album folder for the same release.
        _stabilize_scraped_meta(first_meta, first_hint, lock_album=bool(first_hint.get("album")), lock_album_artist=bool(first_hint.get("album_artist")))
        _enrich_from_local_assets(source_audio_files[0], first_meta)
    meta_cache[os.path.basename(source_audio_files[0])] = first_meta
    organize_artist = (first_meta.album_artist or first_meta.artist) if first_meta else ""
    organize_album = first_meta.album if first_meta else ""
    # Album folders are owned by a stable album artist, not by each track artist.
    # If this album already exists, reuse the first/primary singer from the existing album;
    # otherwise take the first singer from the current metadata. This prevents
    # albums with guest/different track artists from being split into multiple folders.
    pre_db = SessionLocal()
    try:
        canonical_artist = canonical_album_artist(pre_db, organize_album, organize_artist)
    finally:
        pre_db.close()
    if canonical_artist:
        organize_artist = canonical_artist
    if first_meta and organize_artist:
        first_meta.album_artist = organize_artist

    # Step 2: Hardlink to library
    linked_files = hardlink_to_library(content_path, artist=organize_artist, album=organize_album)
    if not linked_files:
        logger.warning(f"No audio files linked from {content_path}")
        if should_mark_processed:
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
                # For single-file online downloads, the source result has correct title/artist
                # while the filename may be "title - artist", not "artist - title".
                online_hint = metadata_hint if len(linked_files) == 1 else {}
                existing_hint = read_existing_tags(file_path)
                use_hint = _merge_hints(online_hint, existing_hint)
                # 同一专辑下的后续曲目，用第一首确定下来的 album/artist 当强约束，
                # 避免被其他专辑同名的高分候选带走
                shared_album = (first_meta.album if first_meta else "") or use_hint.get("album") or ""
                shared_artist = (
                    (first_meta.album_artist or first_meta.artist) if first_meta else ""
                ) or primary_artist(use_hint.get("album_artist") or use_hint.get("artist") or "")
                audio_meta_hint = read_audio_metadata(file_path)
                meta = _scrape_file(
                    file_path,
                    title_hint=use_hint.get("title") or "",
                    artist_hint=use_hint.get("artist") or shared_artist,
                    album_hint=shared_album,
                    year_hint=use_hint.get("year") or metadata_hint.get("year"),
                    duration_hint=audio_meta_hint.get("duration"),
                    track_hint=use_hint.get("track_number"),
                    context=scrape_context,
                ) or _meta_from_hint(_merge_hints(use_hint, {"album": shared_album, "album_artist": shared_artist}))
                if meta:
                    # For later tracks in the same package, lock album/folder
                    # identity to the first track / local package hint, but keep
                    # per-track artist/title unless the scraper romanized a
                    # trusted Chinese filename/tag.
                    stable_hint = _merge_hints(use_hint, {"album": shared_album, "album_artist": shared_artist})
                    _stabilize_scraped_meta(meta, stable_hint, lock_album=bool(shared_album), lock_album_artist=bool(shared_artist))
                    _enrich_from_local_assets(file_path, meta)
                meta_cache[os.path.basename(file_path)] = meta
            audio_meta = read_audio_metadata(file_path)
            if meta:
                tagged_path = tag_file(file_path, meta)
                if isinstance(tagged_path, str) and tagged_path:
                    file_path = tagged_path
                # Re-read after tagging so duration/bitrate/sample-rate are cached with final file state.
                audio_meta = {**audio_meta, **read_audio_metadata(file_path)}
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
                    "duration": audio_meta.get("duration"),
                })

                _upsert_music_file(
                    db,
                    task_id=task.id if task else None,
                    file_path=file_path,
                    link_path=file_path,
                    scraped=True,
                    meta=meta,
                    audio_meta=audio_meta,
                )
            else:
                _upsert_music_file(
                    db,
                    task_id=task.id if task else None,
                    file_path=file_path,
                    link_path=file_path,
                    scraped=False,
                    meta=None,
                    audio_meta=audio_meta,
                )

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

    if should_mark_processed:
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
            _mark_task_failed(torrent.get("hash", ""), str(e))
