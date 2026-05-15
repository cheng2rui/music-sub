"""Logs API routes."""
import os
from pathlib import Path
from fastapi import APIRouter, Query

router = APIRouter()

LOG_DIR = Path(__file__).parent.parent.parent / "logs"


@router.get("/")
def get_logs(lines: int = Query(default=200, ge=1, le=2000), level: str = ""):
    """Get recent log lines, optionally filtered by level."""
    log_file = LOG_DIR / "music_sub.log"
    if not log_file.exists():
        return {"lines": [], "total": 0}

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception:
        return {"lines": [], "total": 0}

    # Filter by level if specified
    if level:
        level_upper = level.upper()
        all_lines = [l for l in all_lines if f"[{level_upper}]" in l]

    # Return last N lines
    recent = all_lines[-lines:]
    return {"lines": [l.rstrip() for l in recent], "total": len(all_lines)}


@router.delete("/")
def clear_logs():
    """Clear log file."""
    log_file = LOG_DIR / "music_sub.log"
    if log_file.exists():
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("")
    return {"ok": True, "message": "日志已清空"}
