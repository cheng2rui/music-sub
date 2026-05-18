"""Delete files and/or empty folders tool."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview


def _collect_dirs(paths: list[str]) -> set[str]:
    """Collect all unique parent directories from file paths."""
    dirs: set[str] = set()
    for p in paths:
        if not p:
            continue
        dirs.add(str(Path(p).parent))
        # Walk up and collect all ancestors.
        parent = Path(p).parent
        while True:
            parent = parent.parent
            if not parent or str(parent) == parent:  # reached root
                break
            dirs.add(str(parent))
    return dirs


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
    library_root = options.get("library_root", "/music")
    delete_files = options.get("delete_files", False)
    delete_empty_dirs = options.get("delete_empty_dirs", True)

    # Collect all files that would be deleted.
    file_items: list[PreviewItem] = []
    dir_items: list[PreviewItem] = []
    paths = [f.file_path for f in files if f.file_path]

    if delete_files and paths:
        for f in files:
            if not f.file_path or not os.path.exists(f.file_path):
                continue
            size = 0
            try:
                size = os.path.getsize(f.file_path)
            except OSError:
                pass
            file_items.append(PreviewItem(
                file_id=f.id,
                label=Path(f.file_path).name,
                before={"file_path": f.file_path},
                after={"deleted": True},
                would_change=True,
                reason=f"删除文件 ({(size // 1024)}KB)",
            ))

    if delete_empty_dirs:
        dirs = _collect_dirs(paths)
        empty_dirs = _find_empty_dirs(dirs, library_root)
        for dir_path, depth, label in empty_dirs:
            dir_items.append(PreviewItem(
                file_id=None,
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
    library_root = options.get("library_root", "/music")
    delete_files = options.get("delete_files", False)
    delete_empty_dirs = options.get("delete_empty_dirs", True)

    deleted_files = 0
    deleted_dirs = 0
    failed_files = 0
    failed_dirs = 0

    file_ids_to_delete: set[int] = set()

    if delete_files:
        for idx, f in enumerate(files):
            if not f.file_path:
                continue
            fp = Path(f.file_path)
            if not fp.exists():
                continue
            try:
                fp.unlink()
                deleted_files += 1
                file_ids_to_delete.add(f.id)
                on_progress(idx + 1, f"已删除: {fp.name}")
            except OSError as e:
                failed_files += 1
                on_progress(idx + 1, f"删除失败: {fp.name}: {e}")

    if delete_empty_dirs:
        paths = [f.file_path for f in files if f.file_path]
        dirs = _collect_dirs(paths)
        empty_dirs = _find_empty_dirs(dirs, library_root)
        for idx, (dir_path, _, _) in enumerate(empty_dirs):
            try:
                shutil.rmtree(dir_path)
                deleted_dirs += 1
                on_progress(idx + 1, f"已删除空目录: {Path(dir_path).name}")
            except OSError as e:
                failed_dirs += 1
                on_progress(idx + 1, f"删除目录失败: {dir_path}: {e}")

    # Remove DB rows for deleted files.
    if file_ids_to_delete:
        try:
            db.query(MusicFile).filter(MusicFile.id.in_(file_ids_to_delete)).delete(synchronize_session=False)
            db.commit()
        except Exception as e:
            logger.warning(f"[delete_files] DB row delete failed: {e}")
            db.rollback()

    return {
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "failed_files": failed_files,
        "failed_dirs": failed_dirs,
        "total": deleted_files + deleted_dirs,
    }