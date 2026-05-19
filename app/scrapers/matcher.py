"""Metadata candidate scoring utilities inspired by music-tag-web smart tag."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.scrapers.base import MusicMeta


_SEPARATORS = re.compile(r"[\s\-_·・•,，、/\\|:：;；'\"“”‘’()（）\[\]【】{}<>《》]+")
try:
    from opencc import OpenCC
    _T2S = OpenCC("t2s").convert
except Exception:  # pragma: no cover - optional dependency fallback
    # Tiny fallback for common Traditional/Simplified chars so scoring still
    # benefits even when the optional OpenCC package is missing in dev shells.
    _COMMON_T2S = str.maketrans({
        "後": "后", "來": "来", "臺": "台", "台": "台", "灣": "湾", "國": "国",
        "愛": "爱", "夢": "梦", "風": "风", "雲": "云", "與": "与", "為": "为",
        "無": "无", "萬": "万", "裏": "里", "裡": "里", "說": "说", "聽": "听",
        "樂": "乐", "發": "发", "髮": "发", "過": "过", "還": "还", "這": "这",
        "那": "那", "時": "时", "開": "开", "關": "关", "長": "长", "會": "会",
        "個": "个", "們": "们", "妳": "你", "祢": "你", "歲": "岁", "聲": "声",
        "葉": "叶", "島": "岛", "馬": "马", "龍": "龙", "劉": "刘", "張": "张",
        "陳": "陈", "楊": "杨", "黃": "黄", "鄧": "邓", "蕭": "萧", "謝": "谢",
    })
    _T2S = lambda text: str(text or "").translate(_COMMON_T2S)
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
    value = _T2S(unicodedata.normalize("NFKC", value or "")).lower().strip()
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


def _year_score(expected: int | str | None, actual: int | str | None) -> float:
    def parse(v) -> int:
        if not v:
            return 0
        m = re.search(r"\d{4}", str(v))
        return int(m.group(0)) if m else 0
    e, a = parse(expected), parse(actual)
    if not e or not a:
        return 0.0
    delta = abs(e - a)
    if delta == 0:
        return 1.0
    if delta <= 1:
        return 0.7
    if delta <= 3:
        return 0.35
    return 0.0


def _duration_score(expected: float | int | None, actual: float | int | None) -> float:
    try:
        e, a = float(expected or 0), float(actual or 0)
    except Exception:
        return 0.0
    if e <= 0 or a <= 0:
        return 0.0
    delta = abs(e - a)
    if delta <= 2:
        return 1.0
    if delta <= 5:
        return 0.75
    if delta <= 10:
        return 0.45
    # For very long tracks, tolerate a small relative drift.
    return max(0.0, 1.0 - delta / max(e, a)) if delta / max(e, a) <= 0.08 else 0.0


def _track_score(expected: int | str | None, actual: int | str | None) -> float:
    def parse(v) -> int:
        if not v:
            return 0
        m = re.search(r"\d+", str(v))
        return int(m.group(0)) if m else 0
    e, a = parse(expected), parse(actual)
    if not e or not a:
        return 0.0
    return 1.0 if e == a else 0.0


def score_meta(meta: MusicMeta, title_hint: str, artist_hint: str = "", album_hint: str = "",
               year_hint: int | str | None = None, duration_hint: float | int | None = None,
               track_hint: int | str | None = None) -> ScoredMeta:
    """Score one metadata result for a target song."""
    title = text_score(title_hint, meta.title)
    artist = artist_score(artist_hint, meta.artist or meta.album_artist)
    album = text_score(album_hint, meta.album) if album_hint else 0.0
    year = _year_score(year_hint, meta.year)
    duration = _duration_score(duration_hint, getattr(meta, "duration", 0.0))
    track = _track_score(track_hint, meta.track_number)

    # Keep the old title/artist behavior dominant, then add small factual boosts.
    score = title * 0.52
    reasons = [f"title={title:.2f}"]
    if artist_hint:
        score += artist * 0.26
        reasons.append(f"artist={artist:.2f}")
    else:
        title_artist = artist_score(title_hint, meta.artist)
        score += title_artist * 0.08
        reasons.append(f"title_artist={title_artist:.2f}")
    if album_hint:
        score += album * 0.14
        reasons.append(f"album={album:.2f}")
        if album < 0.5:
            score -= 0.15
            reasons.append("album_mismatch")
    else:
        score += 0.03 if (meta.album or "").strip() else 0.0
    if year_hint:
        score += year * 0.04
        reasons.append(f"year={year:.2f}")
    if duration_hint:
        score += duration * 0.10
        reasons.append(f"duration={duration:.2f}")
        if getattr(meta, "duration", 0.0) and duration < 0.45:
            score -= 0.08
            reasons.append("duration_mismatch")
    if track_hint:
        score += track * 0.03
        reasons.append(f"track={track:.2f}")

    penalty, penalty_reasons = _quality_penalty(meta, title_hint, artist_hint)
    score -= penalty
    reasons.extend(penalty_reasons)
    return ScoredMeta(meta=meta, score=max(0.0, min(1.0, score)), reasons=reasons)


def choose_best(candidates: list[MusicMeta], title_hint: str, artist_hint: str = "", album_hint: str = "",
                year_hint: int | str | None = None, duration_hint: float | int | None = None,
                track_hint: int | str | None = None) -> ScoredMeta | None:
    """Return the best candidate above a conservative threshold."""
    if not candidates:
        return None
    scored = [score_meta(m, title_hint, artist_hint, album_hint, year_hint, duration_hint, track_hint) for m in candidates]
    scored.sort(key=lambda item: item.score, reverse=True)
    best = scored[0]
    if best.score < (0.48 if artist_hint else 0.42):
        return None
    return best
