"""High-level entry point that runs the full PT search chain."""
from __future__ import annotations

import logging
from typing import Iterable, Optional

import app.config as cfg_module
from app.services.pt_search.executor import SiteExecutor
from app.services.pt_search.models import QueryPlan, SearchRequest, SearchResponse, ScoredTorrent
from app.services.pt_search.normalizer import merge_results
from app.services.pt_search.planner import plan_queries
from app.services.pt_search.ranker import rank
from app.sites.base import BaseSite
from app.sites.dismusic import DisMusicSite
from app.sites.mteam import MTeamSite
from app.sites.opencd import OpenCDSite
from app.sites.ptclub import PTClubSite

logger = logging.getLogger(__name__)


SITE_CLASSES: dict[str, type[BaseSite]] = {
    "mteam": MTeamSite,
    "opencd": OpenCDSite,
    "ptclub": PTClubSite,
    "dismusic": DisMusicSite,
}


class MusicSearchChain:
    """Orchestrate planner + executor + normalizer + ranker."""

    def __init__(self, *, max_workers: int = 4, site_timeout: float = 15.0) -> None:
        self.max_workers = max_workers
        self.site_timeout = site_timeout

    # ------------------------------------------------------------------
    def search(self, req: SearchRequest) -> SearchResponse:
        plans = plan_queries(req)
        if not plans:
            return SearchResponse(queries=[])

        site_names = self._resolve_sites(req.sites)
        executor = SiteExecutor(
            site_names,
            self._site_factory,
            max_workers=self.max_workers,
            site_timeout=req.timeout or self.site_timeout,
        )
        raw, statuses = executor.run(plans)

        deduped = merge_results(raw)
        weight_lookup = self._weight_lookup(plans)
        scored = rank(deduped, req, weight_lookup)

        # Drop obvious video noise (kept around earlier so callers can audit).
        scored = [item for item in scored if not item.is_video_like]

        if req.limit:
            scored = scored[: req.limit]

        return SearchResponse(
            results=scored,
            sites=statuses,
            queries=plans,
            total=len(scored),
        )

    # ------------------------------------------------------------------
    def _resolve_sites(self, requested: Iterable[str] | None) -> list[str]:
        configured = list(cfg_module.config.sites.keys())
        if not requested:
            return [name for name in configured if self._site_factory(name) is not None]
        names = [name for name in requested if name in SITE_CLASSES]
        return [name for name in names if self._site_factory(name) is not None]

    @staticmethod
    def _weight_lookup(plans: list[QueryPlan]) -> dict[str, float]:
        # Title -> weight is too aggressive; keep weight=1.0 by default and
        # let the ranker honor query weight only when the title equals a plan.
        return {plan.keyword: plan.weight for plan in plans}

    @staticmethod
    def _site_factory(name: str) -> Optional[BaseSite]:
        cfg = cfg_module.config.sites.get(name)
        if not cfg or not cfg.enabled or not cfg.url:
            return None
        cls = SITE_CLASSES.get(name)
        if not cls:
            return None
        kwargs = {"url": cfg.url}
        if cfg.api_key:
            kwargs["api_key"] = cfg.api_key
        if cfg.token:
            kwargs["token"] = cfg.token
        if cfg.cookie:
            kwargs["cookie"] = cfg.cookie
        try:
            return cls(**kwargs)
        except Exception as exc:
            logger.error("[pt_search] failed to build site %s: %s", name, exc)
            return None


def search_with_chain(
    keyword: str,
    sites: list[str] | None = None,
    *,
    type: str = "keyword",
    artist: str = "",
    album: str = "",
    title: str = "",
    quality: str = "any",
    limit: int = 60,
) -> SearchResponse:
    """Convenience wrapper used by API/orchestrator code."""
    chain = MusicSearchChain()
    return chain.search(SearchRequest(
        keyword=keyword,
        sites=sites or [],
        type=type,
        artist=artist,
        album=album,
        title=title,
        quality=quality,
        limit=limit,
    ))
