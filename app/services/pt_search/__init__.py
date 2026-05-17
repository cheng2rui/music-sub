"""MusicSub PT search chain.

灵感来自 MoviePilot 的搜索链：QueryPlanner -> SiteExecutor -> Normalizer -> Ranker。
模块对外暴露轻量接口，旧的 ``app.services.searcher`` 仍然可以继续工作。
"""

from app.services.pt_search.models import (
    QueryPlan,
    SearchRequest,
    SearchResponse,
    SiteSearchStatus,
    ScoredTorrent,
)
from app.services.pt_search.chain import MusicSearchChain

__all__ = [
    "MusicSearchChain",
    "QueryPlan",
    "SearchRequest",
    "SearchResponse",
    "SiteSearchStatus",
    "ScoredTorrent",
]
