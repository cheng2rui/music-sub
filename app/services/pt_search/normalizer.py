"""Result normalizer: detect format/quality and merge duplicates."""
from __future__ import annotations

import re

from app.sites.base import TorrentInfo


_FORMAT_HINTS: list[tuple[str, str]] = [
    ("flac", "FLAC"),
    ("alac", "ALAC"),
    ("ape", "APE"),
    ("wav", "WAV"),
    ("dsd", "DSD"),
    ("dsf", "DSD"),
    ("dff", "DSD"),
    ("aac", "AAC"),
    ("m4a", "M4A"),
    ("mp3", "MP3"),
    ("ogg", "OGG"),
]

_QUALITY_RULES: list[tuple[str, str]] = [
    (r"\b24bit\b|\b24-bit\b|hi-?res|hires", "Hi-Res"),
    (r"flac|ape|wav|alac|dsd|dsf|dff|无损|無損|lossless", "Lossless"),
    (r"\b320(\s*kbps)?\b", "MP3-320"),
    (r"\b256(\s*kbps)?\b", "MP3-256"),
    (r"\b192(\s*kbps)?\b", "MP3-192"),
    (r"\bv0\b|vbr", "MP3-VBR"),
]


def detect_format(title: str) -> str:
    text = (title or "").lower()
    for token, label in _FORMAT_HINTS:
        if token in text:
            return label
    return ""


def detect_quality(title: str) -> str:
    text = (title or "").lower()
    for pattern, label in _QUALITY_RULES:
        if re.search(pattern, text):
            return label
    return ""


def fingerprint(torrent: TorrentInfo) -> str:
    """Stable id for dedup across sites/queries."""
    title = (torrent.title or "").lower().strip()
    return f"{torrent.site}|{torrent.torrent_id}|{title}"


def merge_results(items: list[TorrentInfo]) -> list[TorrentInfo]:
    """Drop exact duplicates, keep the first occurrence per (site, id, title)."""
    seen: dict[str, TorrentInfo] = {}
    for item in items:
        key = fingerprint(item)
        if key in seen:
            continue
        seen[key] = item
    return list(seen.values())
