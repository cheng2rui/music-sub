"""Query planner: turn one user keyword into a small set of PT-friendly queries."""
from __future__ import annotations

import re

from app.services.pt_search.models import QueryPlan, SearchRequest


_DASH_TOKENS = re.compile(r"[\u3000\u00A0]+")
_MULTI_SPACE = re.compile(r"\s{2,}")


def _normalize(text: str) -> str:
    cleaned = _DASH_TOKENS.sub(" ", text or "").strip()
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    return cleaned


def _split_words(text: str) -> list[str]:
    return [w for w in re.split(r"[\s_/]+", text) if w]


def plan_queries(req: SearchRequest, *, max_plans: int = 3) -> list[QueryPlan]:
    """Build at most ``max_plans`` query variants for the request.

    Order of preference: exact > dash > reverse > broad. Each plan keeps a
    weight used by the ranker to penalize broader matches.
    """
    keyword = _normalize(req.keyword)
    if not keyword:
        return []

    plans: list[QueryPlan] = [QueryPlan(keyword=keyword, mode="exact", weight=1.0)]
    seen = {keyword.lower()}

    def _push(text: str, mode: str, weight: float) -> None:
        text = _normalize(text)
        key = text.lower()
        if not text or key in seen:
            return
        seen.add(key)
        plans.append(QueryPlan(keyword=text, mode=mode, weight=weight))

    artist = _normalize(req.artist)
    album = _normalize(req.album)
    title = _normalize(req.title)

    # Album-style query: prefer "artist album" / "album artist" pairs.
    if artist and album:
        _push(f"{artist} {album}", "exact", 1.0)
        _push(f"{artist} - {album}", "dash", 0.95)
        _push(f"{album} {artist}", "reverse", 0.9)
    elif artist and title:
        _push(f"{artist} {title}", "exact", 1.0)
        _push(f"{title} {artist}", "reverse", 0.9)

    # Generic dash variant for natural keywords like "蔡依林 怪美的".
    words = _split_words(keyword)
    if len(words) >= 2:
        _push(" - ".join(words[:2]), "dash", 0.92)
        _push(" ".join(words[::-1]), "reverse", 0.85)

    # Broad fallback: longest single token (>1 char) keeps PT searches cheap.
    if len(words) > 1:
        longest = max(words, key=len)
        if len(longest) > 1:
            _push(longest, "broad", 0.7)

    return plans[:max_plans]
