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
    split_audio as split_audio_mod,
    zh_convert as zh_convert_mod,
    fix_garble as fix_garble_mod,
    cue_candidates as cue_candidates_mod,
    album_artist as album_artist_mod,
    delete_files as delete_files_mod,
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
    "album_artist": {
        "label": "专辑艺人修复",
        "description": "只修复 album_artist，不改 track artist；用于把历史库里被 feat./单曲艺人拆开的专辑合并回同一张。",
        "preview": album_artist_mod.preview,
        "apply": album_artist_mod.apply,
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
    "split_audio": {
        "label": "分割音轨",
        "description": "根据同名 .cue 把整轨 FLAC/APE/WAV 用 ffmpeg 拆成分轨。",
        "preview": split_audio_mod.preview,
        "apply": split_audio_mod.apply,
    },
    "zh_t2s": {
        "label": "繁体转简体",
        "description": "用 OpenCC t2s 把标题/艺人/专辑/风格里的繁体中文转为简体。",
        "preview": zh_convert_mod.preview_to_simplified,
        "apply": zh_convert_mod.apply_to_simplified,
    },
    "zh_s2t": {
        "label": "简体转繁体",
        "description": "用 OpenCC s2t 把标题/艺人/专辑/风格里的简体中文转为繁体。",
        "preview": zh_convert_mod.preview_to_traditional,
        "apply": zh_convert_mod.apply_to_traditional,
    },
    "fix_garble": {
        "label": "乱码修复",
        "description": "检测 GBK/UTF-8 被 latin-1 误读产生的乱码，尝试还原。",
        "preview": fix_garble_mod.preview,
        "apply": fix_garble_mod.apply,
    },
    "cue_candidates": {
        "label": "CUE整轨候选",
        "description": "查找带 .cue 的整轨音频，并批量拆成分轨。",
        "preview": cue_candidates_mod.preview,
        "apply": cue_candidates_mod.apply,
    },
    "delete_files": {
        "label": "删除文件",
        "description": "删除选中的文件，并清理由此产生的空目录。",
        "preview": delete_files_mod.preview,
        "apply": delete_files_mod.apply,
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
            summary = apply_fn(db, files, options, lambda *_: None)
            db.commit()
            return summary
        except Exception:
            db.rollback()
            raise
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
