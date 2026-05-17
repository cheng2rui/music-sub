"""Concurrent site executor with timeout + structured per-site status."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, Iterable

from app.services.pt_search.models import QueryPlan, SiteSearchStatus
from app.sites.base import BaseSite, TorrentInfo


logger = logging.getLogger(__name__)


SiteFactory = Callable[[str], BaseSite | None]


class SiteExecutor:
    """Run multiple sites in parallel and collect structured per-site status."""

    def __init__(
        self,
        site_names: Iterable[str],
        site_factory: SiteFactory,
        *,
        max_workers: int = 4,
        site_timeout: float = 15.0,
    ) -> None:
        self.site_names = [name for name in site_names if name]
        self.site_factory = site_factory
        self.max_workers = max(1, min(max_workers, max(1, len(self.site_names))))
        self.site_timeout = site_timeout

    def run(self, plans: list[QueryPlan]) -> tuple[list[TorrentInfo], list[SiteSearchStatus]]:
        if not self.site_names:
            return [], []
        if not plans:
            return [], [SiteSearchStatus(site=name, ok=True) for name in self.site_names]

        results: list[TorrentInfo] = []
        statuses: list[SiteSearchStatus] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._search_site, name, plans): name
                for name in self.site_names
            }
            for future, name in list(futures.items()):
                try:
                    site_results, status = future.result(timeout=self.site_timeout * (len(plans) + 1))
                except FutureTimeout:
                    statuses.append(SiteSearchStatus(site=name, ok=False, error="timeout"))
                    continue
                except Exception as exc:  # pragma: no cover - defensive logging only
                    logger.exception("[pt_search] %s crashed", name)
                    statuses.append(SiteSearchStatus(site=name, ok=False, error=str(exc)))
                    continue
                statuses.append(status)
                results.extend(site_results)

        return results, statuses

    # ------------------------------------------------------------------
    def _search_site(self, name: str, plans: list[QueryPlan]) -> tuple[list[TorrentInfo], SiteSearchStatus]:
        site = self.site_factory(name)
        if site is None:
            return [], SiteSearchStatus(site=name, ok=False, error="not configured")

        started = time.monotonic()
        merged: dict[str, TorrentInfo] = {}
        used_queries: list[str] = []
        last_error = ""

        for plan in plans:
            try:
                items = site.search(plan.keyword) or []
            except Exception as exc:
                logger.warning("[pt_search] %s query %r failed: %s", name, plan.keyword, exc)
                last_error = str(exc) or last_error
                continue
            used_queries.append(plan.keyword)
            for item in items:
                key = f"{item.torrent_id}|{(item.title or '').lower()}"
                if key in merged:
                    continue
                merged[key] = item
            # Stop early once we have enough useful results from the strongest plan.
            if plan.weight >= 0.95 and len(merged) >= 30:
                break

        elapsed = round(time.monotonic() - started, 3)
        status = SiteSearchStatus(
            site=name,
            ok=True if merged else not last_error,
            count=len(merged),
            seconds=elapsed,
            error="" if merged else last_error,
            queries=used_queries,
        )
        if not merged and last_error:
            status.ok = False
        return list(merged.values()), status
