"""Library tool box: identify / retag / split_meta / organize / dedupe.

Each tool exposes ``preview`` (dry-run) and ``apply`` (mutating) entry points.
Apply runs are dispatched through the existing :mod:`app.services.scrape_jobs`
runner so progress is visible at ``/api/library/jobs/{id}``.
"""
from app.services.library_tools.base import (
    PreviewItem,
    ToolPreview,
    ToolError,
)
from app.services.library_tools.registry import (
    list_tools,
    get_tool,
    preview as tool_preview,
    apply as tool_apply,
)

__all__ = [
    "PreviewItem",
    "ToolPreview",
    "ToolError",
    "list_tools",
    "get_tool",
    "tool_preview",
    "tool_apply",
]
