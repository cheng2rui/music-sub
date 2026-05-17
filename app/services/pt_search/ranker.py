"""Music-aware ranker for normalized PT results."""
from __future__ import annotations

import re

from app.services.pt_search.models import ScoredTorrent, SearchRequest
from app.services.pt_search.normalizer import detect_format, detect_quality
from app.sites.base import TorrentInfo


# Hard signals that almost always mean a video release rather than audio.
_VIDEO_TERMS = (
    "mp4", "mkv", "avi", "web-dl", "webrip", "bluray", "blu-ray",
    "bdrip", "dvdrip", "hdtv", "hdrip", "dvdiso", "bdiso",
    "h.264", "h264", "h.265", "h265", "x264", "x265", "hevc", "avc",
    "2160p", "1080p", "720p", "576p", "480p", "4k uhd", "4kuhd", "uhd ",
    "60fps", "hdr", "remux", "3d-bd",
    "music video", " mv ", "[mv]",
)

_FORMAT_BONUS: dict[str, float] = {
    "FLAC": 16,
    "ALAC": 14,
    "WAV": 12,
    "APE": 12,
    "DSD": 16,
    "MP3": 8,
    "AAC": 6,
    "M4A": 6,
    "OGG": 4,
}

_QUALITY_BONUS: dict[str, float] = {
    "Hi-Res": 10,
    "Lossless": 8,
    "MP3-320": 6,
    "MP3-256": 4,
    "MP3-192": 1,
    "MP3-VBR": 2,
}

_TYPE_MAX_SIZE = {
    "song": 500 * 1024 * 1024,
    "album": 8 * 1024 * 1024 * 1024,
    "keyword": 3 * 1024 * 1024 * 1024,
    "artist": 8 * 1024 * 1024 * 1024,
}


def _looks_like_video(title: str) -> bool:
    lower = " " + (title or "").lower() + " "
    return any(term in lower for term in _VIDEO_TERMS)


def _term_in_title(title: str, term: str) -> bool:
    if not term:
        return False
    return term.lower() in title.lower()


def _coverage_score(title: str, words: list[str]) -> float:
    if not words:
        return 0.0
    hits = sum(1 for w in words if w and w.lower() in title.lower())
    return hits / len(words)


def score_one(item: TorrentInfo, req: SearchRequest, query_weight: float) -> ScoredTorrent:
    title = item.title or ""
    fmt = detect_format(title)
    quality = detect_quality(title)
    is_video = _looks_like_video(title)

    score = 0.0
    reasons: list[str] = []

    # Title coverage: how many of the user's words show up.
    words = [w for w in re.split(r"[\s_/]+", req.keyword or "") if w]
    coverage = _coverage_score(title, words)
    if coverage:
        score += coverage * 30
        reasons.append(f"title={coverage:.2f}")

    # Targeted artist/album/title matches.
    if _term_in_title(title, req.artist):
        score += 14
        reasons.append("artist")
    if _term_in_title(title, req.album):
        score += 18
        reasons.append("album")
    if _term_in_title(title, req.title):
        score += 12
        reasons.append("song")

    # Media format / quality.
    bonus = _FORMAT_BONUS.get(fmt, 0)
    if bonus:
        score += bonus
        reasons.append(f"fmt={fmt}")
    qbonus = _QUALITY_BONUS.get(quality, 0)
    if qbonus:
        score += qbonus
        reasons.append(f"quality={quality}")

    # Subscription quality preference.
    if req.quality == "flac" and fmt in {"FLAC", "ALAC", "APE", "WAV", "DSD"}:
        score += 6
        reasons.append("pref-flac")
    if req.quality == "mp3" and fmt == "MP3":
        score += 4
        reasons.append("pref-mp3")

    # Free / promo / health.
    if item.free:
        score += 8
        reasons.append("free")
    if item.seeders >= 10:
        score += 6
        reasons.append("seeders+")
    elif item.seeders >= 1:
        score += 2
    if item.seeders == 0:
        score -= 4
        reasons.append("no-seeder")

    # Size sanity.
    max_size = _TYPE_MAX_SIZE.get(req.type)
    if max_size and item.size and item.size > max_size:
        score -= 12
        reasons.append("oversize")

    # Video penalty.
    if is_video:
        score -= 80
        reasons.append("video")

    # Query weight: broader queries are penalized lightly.
    score *= query_weight

    return ScoredTorrent(
        torrent=item,
        score=round(score, 2),
        quality=quality,
        media_format=fmt,
        is_video_like=is_video,
        reasons=reasons,
    )


def rank(items: list[TorrentInfo], req: SearchRequest, query_weights: dict[str, float]) -> list[ScoredTorrent]:
    scored: list[ScoredTorrent] = []
    for item in items:
        weight = query_weights.get(item.title, 1.0)
        scored.append(score_one(item, req, weight))
    scored.sort(key=lambda s: (s.score, s.torrent.seeders), reverse=True)
    return scored
