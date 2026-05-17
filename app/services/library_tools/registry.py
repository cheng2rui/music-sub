"""Tool registry + dry-run / apply dispatch."""
from __future__ import annotations

import logging
from typing import Any

from app.db import SessionLocal
from app.services.library_tools.base import (
    ApplyFn,
    PreviewFn,
    ToolError,
    ToolPreview,
    resolve_files,
)
from app.services.library_tools import (
    identify as identify_mod,
    retag as retag_mod,
    split_meta as split_meta_mod,
    organize as organize_mod,
    dedupe as dedupe_mod,
)
from app.services.scrape_jobs import runner as job_runner, JobStep, mark_step

logger = logging.getLogger(__name__)


_TOOLS: dict[str, dict[str, Any]] = {
    "identify": {
        "label": "\u8bc6\u522b\u6574\u7406",
        "description": "\u4ece\u8d44\u6599\u5e93\u8def\u5f84\u548c\u6587\u4ef6\u540d\u63a8\u51fa artist/album/title/track \u5e76\u5199\u56de DB\uff08\u4e0d\u52a8\u539f\u59cb\u6587\u4ef6\u3002\uff09",
        "preview": identify_mod.preview,
        "apply": identify_mod.apply,
    },
    "retag": {
        "label": "\u4fee\u6539\u6807\u7b7e",
        "description": "\u6309\u6a21\u677f / \u56fa\u5b9a\u503c \u91cd\u5199 title / artist / album / year / genre\uff0c\u540c\u6b65\u5230 DB \u548c\u97f3\u9891\u6587\u4ef6\u3002",
        "preview": retag_mod.preview,
        "apply": retag_mod.apply,
    },
    "split_meta": {
        "label": "\u62c6\u5206\u5143\u6570\u636e",
        "description": "\u4ece\u6df7\u5728 title \u91cc\u7684 artist - title / title (Live) \u7b49\u683c\u5f0f\u62c6\u51fa\u5404\u5b57\u6bb5\u3002",
        "preview": split_meta_mod.preview,
        "apply": split_meta_mod.apply,
    },
    "organize": {
        "label": "\u6574\u7406\u6587\u4ef6",
        "description": "\u6309 {artist}/{album}/{disc}-{track:02d} {title}.{ext} \u7edf\u4e00\u91cd\u547d\u540d / \u79fb\u52a8\u5165\u5e93\u3002",
        "preview": organize_mod.preview,
        "apply": organize_mod.apply,
    },
    "dedupe": {
        "label": "\u91cd\u590d\u6587\u4ef6\u68c0\u67e5",
        "description": "\u68c0\u6d4b\u91cd\u590d\u66f2\u76ee\uff08artist/title/duration/size\uff09\u5e76\u63d0\u4f9b\u4fdd\u7559 / \u5220\u9664\u5efa\u8bae\u3002",
        "preview": dedupe_mod.preview,
        "apply": dedupe_mod.apply,
    },
}


def list_tools() -> list[dict]:
    return [
        {"id": tid, "label": meta["label"], "description": meta["description"]}
        for tid, meta in _TOOLS.items()
    ]


def get_tool(tool_id: str) -> dict[str, Any]:
    if tool_id not in _TOOLS:
        raise ToolError(f"Unknown tool: {tool_id}")
    return _TOOLS[tool_id]


# ---------------------------------------------------------------------------
def preview(tool_id: str, *, file_ids=None, album_artist="", album_name="",
            options: dict[str, Any] | None = None) -> ToolPreview:
    tool = get_tool(tool_id)
    options = options or {}
    db = SessionLocal()
    try:
        files = resolve_files(db, file_ids=file_ids,
                              album_artist=album_artist or None,
                              album_name=album_name or None)
        if not files:
            return ToolPreview(tool=tool_id, summary={"empty": True})
        preview_fn: PreviewFn = tool["preview"]
        return preview_fn(db, files, options)
    finally:
        db.close()


def apply(tool_id: str, *, file_ids=None, album_artist="", album_name="",
          options: dict[str, Any] | None = None, async_mode: bool = True):
    tool = get_tool(tool_id)
    options = options or {}
    apply_fn: ApplyFn = tool["apply"]

    if not async_mode:
        db = SessionLocal()
        try:
            files = resolve_files(db, file_ids=file_ids,
                                  album_artist=album_artist or None,
                                  album_name=album_name or None)
            return apply_fn(db, files, options, lambda *_: None)
        finally:
            db.close()

    # Async path: pre-resolve labels so we can stream per-file progress.
    db = SessionLocal()
    try:
        files = resolve_files(db, file_ids=file_ids,
                              album_artist=album_artist or None,
                              album_name=album_name or None)
    finally:
        db.close()

    file_ids_resolved = [f.id for f in files]
    labels = [f.title or f.file_path for f in files] or [tool_id]

    def runner_fn(job):
        inner_db = SessionLocal()
        try:
            inner_files = resolve_files(inner_db, file_ids=file_ids_resolved or None)
            def on_progress(idx: int, message: str):
                if 0 <= idx < len(job.steps):
                    mark_step(job.steps[idx], "ok" if not message.startswith("err:") else "failed",
                              message[4:] if message.startswith("err:") else message)
                job.progress = min(idx + 1, len(job.steps))
            try:
                summary = apply_fn(inner_db, inner_files, options, on_progress)
                inner_db.commit()
                job.summary = summary
            except Exception as exc:  # pragma: no cover - defensive
                inner_db.rollback()
                logger.exception("[library_tools] apply failed")
                job.status = "failed"
                job.error = str(exc)[:500]
        finally:
            inner_db.close()

    job = job_runner.submit(
        kind=f"library_tool:{tool_id}",
        total=len(file_ids_resolved),
        runner=runner_fn,
        step_labels=labels,
    )
    return job
