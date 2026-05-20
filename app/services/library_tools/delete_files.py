"""Delete files and/or empty folders tool."""
from __future__ import annotations

import datetime
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import MusicFile
from app.services.library_audit import log_library_event
from app.services.library_tools.base import PreviewItem, ToolPreview

logger = logging.getLogger(__name__)


def _collect_dirs(paths: list[str]) -> set[str]:
    """Collect all unique parent directories from file paths, stopping at root."""
    dirs: set[str] = set()
    for p in paths:
        if not p:
            continue
        dp = Path(p).resolve()
        while True:
            parent = dp.parent
            # Stop when parent equals self (can't go higher) or at filesystem root.
            if parent == dp or str(parent) == "/":
                break
            dirs.add(str(parent))
            dp = parent
    return dirs


def _trash_path(file_path: Path, library_root: str) -> Path:
    root = Path(library_root).resolve()
    trash_root = root / ".trash" / datetime.datetime.now().strftime("%Y%m%d")
    try:
        rel = file_path.resolve().relative_to(root)
    except ValueError:
        rel = Path(file_path.name)
    dest = trash_root / rel
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}-{datetime.datetime.now().strftime('%H%M%S')}{dest.suffix}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def _find_empty_dirs(dirs: set[str], library_root: str) -> list[tuple[str, int, str]]:
    """Find empty directories under library_root.
    
    Returns list of (dir_path, depth, parent_preview_label) sorted deepest-first.
    """
    results: list[tuple[str, int, str]] = []
    root = Path(library_root).resolve()
    for d in sorted(dirs, key=lambda x: -x.count(os.sep)):
        dp = Path(d).resolve()
        # Only consider dirs inside the library.
        try:
            dp.relative_to(root)
        except ValueError:
            continue
        if not dp.is_dir():
            continue
        # Only delete truly empty dirs (no subdirs, no files).
        if any(dp.iterdir()):
            continue
        depth = len(dp.relative_to(root).parts)
        label = str(dp.relative_to(root))
        results.append((str(dp), depth, label))
    return results


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    from app.config import config
    library_root = options.get("library_root") or config.paths.library
    delete_files = options.get("delete_files", False)
    delete_empty_dirs = options.get("delete_empty_dirs", True)
    delete_missing_db_rows = options.get("delete_missing_db_rows", True)
    mode = options.get("mode") or ("delete" if options.get("permanent") else "trash")

    # Collect all files that would be deleted or moved to trash.
    file_items: list[PreviewItem] = []
    dir_items: list[PreviewItem] = []
    paths = [f.file_path for f in files if f.file_path]

    if delete_files and paths:
        for f in files:
            if not f.file_path:
                continue
            fp = Path(f.file_path)
            if not fp.is_file():
                if delete_missing_db_rows:
                    file_items.append(PreviewItem(
                        file_id=f.id,
                        file_path=f.file_path,
                        label=fp.name,
                        before={"file_path": f.file_path, "exists": False},
                        after={"db_row_deleted": True},
                        would_change=True,
                        reason="文件不存在，移除库记录",
                    ))
                continue
            size = 0
            try:
                size = os.path.getsize(f.file_path)
            except OSError:
                pass
            file_items.append(PreviewItem(
                file_id=f.id,
                file_path=f.file_path,
                label=fp.name,
                before={"file_path": f.file_path, "exists": True},
                after={"deleted": mode == "delete", "trashed": mode != "delete", "db_row_deleted": True},
                would_change=True,
                reason=f"{'永久删除' if mode == 'delete' else '移入回收站'}文件 ({(size // 1024)}KB)",
            ))

    if delete_empty_dirs:
        dirs = _collect_dirs(paths)
        empty_dirs = _find_empty_dirs(dirs, library_root)
        for dir_path, depth, label in empty_dirs:
            dir_items.append(PreviewItem(
                file_id=None,
                file_path=dir_path,
                label=label,
                before={"dir_path": dir_path},
                after={"deleted": True},
                would_change=True,
                reason=f"删除空目录 (深度{depth})",
            ))

    all_items = file_items + dir_items
    return ToolPreview(
        tool="delete_files",
        items=all_items,
        summary={
            "files": len(file_items),
            "dirs": len(dir_items),
            "total": len(all_items),
        },
    )


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict[str, Any]:
    from app.config import config
    library_root = options.get("library_root") or config.paths.library
    delete_files = options.get("delete_files", False)
    delete_empty_dirs = options.get("delete_empty_dirs", True)
    delete_missing_db_rows = options.get("delete_missing_db_rows", True)
    mode = options.get("mode") or ("delete" if options.get("permanent") else "trash")
    permanent = mode == "delete"

    deleted_files = 0
    trashed_files = 0
    deleted_dirs = 0
    failed_files = 0
    failed_dirs = 0
    removed_db_rows = 0

    file_ids_to_delete: set[int] = set()

    if delete_files:
        for idx, f in enumerate(files):
            if not f.file_path:
                continue
            fp = Path(f.file_path)
            # Use is_file() instead of exists() to handle hardlinks that may be missing.
            # is_file() returns True for symlinks/hardlinks pointing to regular files.
            if not fp.is_file():
                if delete_missing_db_rows:
                    file_ids_to_delete.add(f.id)
                    on_progress(idx, f"文件不存在，已移除库记录: {fp.name}")
                continue
            try:
                if permanent:
                    fp.unlink()
                    deleted_files += 1
                    log_library_event(
                        db=db,
                        action="delete",
                        file_path=str(fp),
                        message="永久删除音乐文件",
                        details={"file_id": f.id, "title": f.title, "artist": f.artist, "album": f.album},
                    )
                    on_progress(idx, f"已永久删除: {fp.name}")
                else:
                    dest = _trash_path(fp, library_root)
                    shutil.move(str(fp), str(dest))
                    trashed_files += 1
                    log_library_event(
                        db=db,
                        action="trash",
                        file_path=str(fp),
                        trash_path=str(dest),
                        message="移入音乐库回收站",
                        details={"file_id": f.id, "title": f.title, "artist": f.artist, "album": f.album},
                    )
                    on_progress(idx, f"已移入回收站: {fp.name}")
                file_ids_to_delete.add(f.id)
            except OSError as e:
                failed_files += 1
                log_library_event(db=db, action="trash" if not permanent else "delete", status="error", file_path=str(fp), message=str(e)[:500], details={"file_id": f.id})
                on_progress(idx, f"删除失败: {fp.name}: {e}")

    if delete_empty_dirs:
        paths = [f.file_path for f in files if f.file_path]
        dirs = _collect_dirs(paths)
        empty_dirs = _find_empty_dirs(dirs, library_root)
        for idx, (dir_path, _, _) in enumerate(empty_dirs):
            try:
                shutil.rmtree(dir_path)
                deleted_dirs += 1
                on_progress(len(files) + idx, f"已删除空目录: {Path(dir_path).name}")
            except OSError as e:
                failed_dirs += 1
                on_progress(len(files) + idx, f"删除目录失败: {dir_path}: {e}")

    # Remove DB rows for deleted files.
    if file_ids_to_delete:
        try:
            removed_db_rows = db.query(MusicFile).filter(MusicFile.id.in_(file_ids_to_delete)).delete(synchronize_session=False)
            db.commit()
        except Exception as e:
            logger.warning(f"[delete_files] DB row delete failed: {e}")
            db.rollback()

    return {
        "deleted_files": deleted_files,
        "trashed_files": trashed_files,
        "deleted_dirs": deleted_dirs,
        "failed_files": failed_files,
        "failed_dirs": failed_dirs,
        "removed_db_rows": removed_db_rows,
        "total": deleted_files + trashed_files + deleted_dirs + removed_db_rows,
        "mode": mode,
    }