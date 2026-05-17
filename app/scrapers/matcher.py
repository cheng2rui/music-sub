"""Metadata candidate scoring utilities inspired by music-tag-web smart tag."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.scrapers.base import MusicMeta


_SEPARATORS = re.compile(r"[\s\-_·・•,，、/\\|:：;；'\"“”‘’()（）\[\]【】{}<>《》]+")
_EXTRA_MARKERS = re.compile(
    r"\b(live|remix|cover|伴奏|demo|karaoke|instrumental|mv|版|现场|演唱会|巡回|remastered?)\b",
    re.IGNORECASE,
)


@dataclass
class ScoredMeta:
    meta: MusicMeta
    score: float
    reasons: list[str]


def normalize_text(value: str | None) -> str:
    """Normalize text for fuzzy matching across punctuation/case/full-width variants."""
    value = unicodedata.normalize("NFKC", value or "").lower().strip()
    value = value.replace("&", "and")
    value = _SEPARATORS.sub("", value)
    return value


def split_artists(value: str | None) -> list[str]:
    """Split common multi-artist strings while preserving non-empty parts."""
    value = unicodedata.normalize("NFKC", value or "")
    parts = re.split(r"\s*(?:/|,|，|、|&| feat\.? | ft\.? | with |和|与)\s*", value, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p and p.strip()]


def text_score(expected: str | None, actual: str | None) -> float:
    """Return 0..1 fuzzy score with exact/substring boosts."""
    e = normalize_text(expected)
    a = normalize_text(actual)
    if not e or not a:
        return 0.0
    if e == a:
        return 1.0
    if e in a or a in e:
        shorter = min(len(e), len(a))
        longer = max(len(e), len(a))
        return max(0.72, shorter / longer)
    return SequenceMatcher(None, e, a).ratio()


def artist_score(expected: str | None, actual: str | None) -> float:
    """Score artists by best pair plus coverage for multi-artist values."""
    expected_parts = split_artists(expected)
    actual_parts = split_artists(actual)
    if not expected_parts or not actual_parts:
        return text_score(expected, actual)
    best_each = []
    for ep in expected_parts:
        best_each.append(max(text_score(ep, ap) for ap in actual_parts))
    coverage = sum(best_each) / len(best_each)
    any_best = max(best_each) if best_each else 0.0
    return max(coverage, any_best * 0.9)


def _quality_penalty(meta: MusicMeta, title_hint: str, artist_hint: str) -> tuple[float, list[str]]:
    """Penalize likely wrong variants without forbidding them."""
    penalty = 0.0
    reasons: list[str] = []
    text = " ".join([meta.title or "", meta.album or ""]).lower()
    hint_text = " ".join([title_hint or "", artist_hint or ""]).lower()
    if _EXTRA_MARKERS.search(text) and not _EXTRA_MARKERS.search(hint_text):
        penalty += 0.08
        reasons.append("variant_penalty")
    if not (meta.album or "").strip():
        penalty += 0.04
        reasons.append("missing_album")
    if not (meta.cover_url or meta.cover_data):
        penalty += 0.02
        reasons.append("missing_cover")
    return penalty, reasons


def score_meta(meta: MusicMeta, title_hint: str, artist_hint: str = "", album_hint: str = "") -> ScoredMeta:
    """Score one metadata result for a target song."""
    title = text_score(title_hint, meta.title)
    artist = artist_score(artist_hint, meta.artist or meta.album_artist)
    album = text_score(album_hint, meta.album) if album_hint else 0.0

    score = title * 0.58
    reasons = [f"title={title:.2f}"]
    if artist_hint:
        score += artist * 0.32
        reasons.append(f"artist={artist:.2f}")
    else:
        # No trusted artist: still lightly prefer candidates whose artist appears in title/filename.
        title_artist = artist_score(title_hint, meta.artist)
        score += title_artist * 0.10
        reasons.append(f"title_artist={title_artist:.2f}")
    if album_hint:
        # 专辑作为强信号：完全匹配加 0.18，未命中且得分低于 0.5 时明显扣分，防止同名其他专辑被选上
        score += album * 0.18
        reasons.append(f"album={album:.2f}")
        if album < 0.5:
            score -= 0.15
            reasons.append("album_mismatch")
    else:
        score += 0.04 if (meta.album or "").strip() else 0.0

    penalty, penalty_reasons = _quality_penalty(meta, title_hint, artist_hint)
    score -= penalty
    reasons.extend(penalty_reasons)
    return ScoredMeta(meta=meta, score=max(0.0, min(1.0, score)), reasons=reasons)


def choose_best(candidates: list[MusicMeta], title_hint: str, artist_hint: str = "", album_hint: str = "") -> ScoredMeta | None:
    """Return the best candidate above a conservative threshold."""
    if not candidates:
        return None
    scored = [score_meta(m, title_hint, artist_hint, album_hint) for m in candidates]
    scored.sort(key=lambda item: item.score, reverse=True)
    best = scored[0]
    if best.score < (0.48 if artist_hint else 0.42):
        return None
    return best
