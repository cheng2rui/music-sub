"""Split single-file audio + .cue into individual tracks via ffmpeg."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import MusicFile
from app.services.library_tools.base import PreviewItem, ToolPreview

logger = logging.getLogger(__name__)


@dataclass
class CueTrack:
    index: int
    title: str
    performer: str
    start_seconds: float


def _read_cue(cue_path: Path) -> tuple[list[CueTrack], dict[str, str]]:
    """Tiny CUE parser. Returns (tracks, album_meta)."""
    encoding_candidates = ["utf-8", "utf-8-sig", "gb18030", "shift_jis", "latin-1"]
    text = ""
    for enc in encoding_candidates:
        try:
            text = cue_path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    album_meta: dict[str, str] = {}
    tracks: list[CueTrack] = []
    current: dict[str, Any] = {}
    in_track = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("TITLE ") and not in_track:
            album_meta["title"] = _strip_quotes(line[6:])
        elif line.upper().startswith("PERFORMER ") and not in_track:
            album_meta["performer"] = _strip_quotes(line[10:])
        elif line.upper().startswith("REM DATE "):
            album_meta["date"] = line[len("REM DATE "):].strip()
        elif line.upper().startswith("REM GENRE "):
            album_meta["genre"] = _strip_quotes(line[len("REM GENRE "):])
        elif line.upper().startswith("TRACK "):
            in_track = True
            if current:
                tracks.append(_finalize_track(current))
            num = re.search(r"TRACK\s+(\d+)", line, re.IGNORECASE)
            current = {"index": int(num.group(1)) if num else len(tracks) + 1}
        elif line.upper().startswith("TITLE ") and in_track:
            current["title"] = _strip_quotes(line[6:])
        elif line.upper().startswith("PERFORMER ") and in_track:
            current["performer"] = _strip_quotes(line[10:])
        elif line.upper().startswith("INDEX 01") and in_track:
            timestamp = line.split()[-1]
            current["start_seconds"] = _parse_msf(timestamp)
    if current:
        tracks.append(_finalize_track(current))
    return tracks, album_meta


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if text.startswith("\"") and text.endswith("\""):
        return text[1:-1]
    return text


def _parse_msf(text: str) -> float:
    parts = text.split(":")
    if len(parts) != 3:
        return 0.0
    minutes, seconds, frames = (int(p) for p in parts)
    return minutes * 60 + seconds + frames / 75.0


def _finalize_track(current: dict[str, Any]) -> CueTrack:
    return CueTrack(
        index=int(current.get("index", 0)),
        title=current.get("title", "") or f"Track {current.get('index', 0):02d}",
        performer=current.get("performer", ""),
        start_seconds=float(current.get("start_seconds", 0.0)),
    )


def _detect_audio_companion(file_path: Path) -> Path | None:
    if not file_path.exists():
        return None
    base = file_path.with_suffix("")
    for ext in (".flac", ".ape", ".wav", ".tta", ".tak"):
        candidate = base.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def _matched_cue(audio_path: Path) -> Path | None:
    candidate = audio_path.with_suffix(".cue")
    if candidate.exists():
        return candidate
    # Same directory: pick first .cue if uniquely linked.
    cues = list(audio_path.parent.glob("*.cue"))
    return cues[0] if len(cues) == 1 else None


def _propose(file: MusicFile, options: dict[str, Any]) -> dict[str, Any] | None:
    if not file.file_path:
        return None
    audio_path = Path(file.file_path)
    cue_path = _matched_cue(audio_path) or (audio_path.parent / (audio_path.stem + ".cue"))
    if not cue_path.exists():
        cue_path = options.get("cue_path") and Path(options["cue_path"])
    if not cue_path or not cue_path.exists():
        return None
    tracks, album_meta = _read_cue(cue_path)
    if len(tracks) <= 1:
        return None
    output_dir = audio_path.parent
    return {
        "audio_path": str(audio_path),
        "cue_path": str(cue_path),
        "tracks": [
            {
                "index": t.index,
                "title": t.title,
                "performer": t.performer or album_meta.get("performer", ""),
                "start_seconds": round(t.start_seconds, 3),
                "out": str(output_dir / f"{t.index:02d} {_safe_name(t.title)}{audio_path.suffix}"),
            }
            for t in tracks
        ],
        "album": album_meta,
    }


_INVALID = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def _safe_name(text: str) -> str:
    cleaned = _INVALID.sub("_", (text or "").strip())
    return cleaned.rstrip(". ") or "track"


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    items: list[PreviewItem] = []
    plans = 0
    for f in files:
        plan = _propose(f, options)
        if not plan:
            items.append(PreviewItem(
                file_id=f.id,
                file_path=f.file_path,
                label=Path(f.file_path).name if f.file_path else str(f.id),
                before={},
                after={},
                would_change=False,
                reason="未发现可拆分的 .cue 或只含单首",
            ))
            continue
        items.append(PreviewItem(
            file_id=f.id,
            file_path=f.file_path,
            label=Path(f.file_path).name if f.file_path else str(f.id),
            before={"file_path": f.file_path},
            after={"tracks": plan["tracks"]},
            would_change=True,
            reason=f"计划拆出 {len(plan['tracks'])} 首",
        ))
        plans += 1
    return ToolPreview(tool="split_audio", items=items, summary={"planned": plans, "total": len(items)})


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    if shutil.which("ffmpeg") is None:
        return {"split": 0, "total": len(files), "error": "ffmpeg 不可用"}
    keep_original = bool(options.get("keep_original", True))
    split_count = 0
    for idx, f in enumerate(files):
        try:
            plan = _propose(f, options)
            if not plan:
                on_progress(idx, "skip: no cue")
                continue
            audio_path = Path(plan["audio_path"])
            tracks = plan["tracks"]
            for ti, track in enumerate(tracks):
                out_path = Path(track["out"])
                if out_path.exists():
                    on_progress(idx, f"err:target exists {out_path}")
                    continue
                start = float(track["start_seconds"])
                end = float(tracks[ti + 1]["start_seconds"]) if ti + 1 < len(tracks) else 0.0
                args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(audio_path),
                        "-ss", f"{start:.3f}"]
                if end > start:
                    args.extend(["-to", f"{end:.3f}"])
                args.extend(["-c", "copy", str(out_path)])
                proc = subprocess.run(args, capture_output=True, text=True)
                if proc.returncode != 0:
                    on_progress(idx, f"err:track {track['index']} ffmpeg failed: {proc.stderr.strip()[:200]}")
                    continue
            if not keep_original:
                trash_dir = audio_path.parent / ".originals"
                trash_dir.mkdir(exist_ok=True)
                shutil.move(str(audio_path), str(trash_dir / audio_path.name))
            split_count += 1
            on_progress(idx, f"split into {len(tracks)} tracks")
        except Exception as exc:
            on_progress(idx, f"err:{exc}")
    return {"split": split_count, "total": len(files)}
