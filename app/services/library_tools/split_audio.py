"""Split single-file audio + .cue into individual tracks via ffmpeg.

The tool is intentionally conservative:
- Preview parses the CUE and shows exact output paths.
- Apply uses ``-ss start -t duration`` semantics to avoid ambiguous ``-to`` cuts.
- Split tracks are tagged from CUE metadata and upserted into MusicFile.
- Local album assets (cover.* / embedded artwork / .cue / .log) are preserved next to the split tracks.
"""
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

from app.config import config
from app.models import MusicFile
from app.scrapers.base import MusicMeta
from app.scrapers.tagger import (
    find_local_cover_data,
    read_audio_metadata,
    read_embedded_cover,
    save_cover,
    tag_file,
)
from app.services.library_tools.base import PreviewItem, ToolPreview

logger = logging.getLogger(__name__)


@dataclass
class CueTrack:
    index: int
    title: str
    performer: str
    start_seconds: float


@dataclass
class CueSheet:
    tracks: list[CueTrack]
    album: dict[str, str]
    audio_file: str = ""


def _read_cue(cue_path: Path) -> tuple[list[CueTrack], dict[str, str]]:
    """Tiny CUE parser. Returns (tracks, album_meta).

    Kept as the public internal shape older code already imports; internally we
    parse through :func:`_read_cue_sheet` so FILE lines are also available.
    """
    sheet = _read_cue_sheet(cue_path)
    return sheet.tracks, sheet.album


def _read_cue_sheet(cue_path: Path) -> CueSheet:
    encoding_candidates = ["utf-8", "utf-8-sig", "gb18030", "big5", "shift_jis", "latin-1"]
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
    audio_file = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        upper = line.upper()
        if not line:
            continue
        if upper.startswith("FILE ") and not audio_file:
            # FILE "album.flac" WAVE
            m = re.match(r'FILE\s+"([^"]+)"', line, re.IGNORECASE) or re.match(r"FILE\s+(\S+)", line, re.IGNORECASE)
            if m:
                audio_file = m.group(1).strip()
        elif upper.startswith("TITLE ") and not in_track:
            album_meta["title"] = _strip_quotes(line[6:])
        elif upper.startswith("PERFORMER ") and not in_track:
            album_meta["performer"] = _strip_quotes(line[10:])
        elif upper.startswith("REM DATE "):
            album_meta["date"] = _strip_quotes(line[len("REM DATE "):])
        elif upper.startswith("REM GENRE "):
            album_meta["genre"] = _strip_quotes(line[len("REM GENRE "):])
        elif upper.startswith("TRACK "):
            in_track = True
            if current:
                tracks.append(_finalize_track(current))
            num = re.search(r"TRACK\s+(\d+)", line, re.IGNORECASE)
            current = {"index": int(num.group(1)) if num else len(tracks) + 1}
        elif upper.startswith("TITLE ") and in_track:
            current["title"] = _strip_quotes(line[6:])
        elif upper.startswith("PERFORMER ") and in_track:
            current["performer"] = _strip_quotes(line[10:])
        elif upper.startswith("INDEX 01") and in_track:
            timestamp = line.split()[-1]
            current["start_seconds"] = _parse_msf(timestamp)
    if current:
        tracks.append(_finalize_track(current))
    tracks.sort(key=lambda t: t.index)
    return CueSheet(tracks=tracks, album=album_meta, audio_file=audio_file)


def _strip_quotes(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith('"') and text.endswith('"'):
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


def _matched_cue(audio_path: Path) -> Path | None:
    candidate = audio_path.with_suffix(".cue")
    if candidate.exists():
        return candidate
    cues = list(audio_path.parent.glob("*.cue"))
    if len(cues) == 1:
        return cues[0]
    # If a CUE FILE line points to this audio file, treat it as matched.
    for cue in cues:
        try:
            sheet = _read_cue_sheet(cue)
        except Exception:
            continue
        if sheet.audio_file and Path(sheet.audio_file).name == audio_path.name:
            return cue
    return _matched_download_cue(audio_path)


def _matched_download_cue(audio_path: Path) -> Path | None:
    """Fallback for older library rows where the .cue stayed in downloads."""
    try:
        download_root = Path(config.paths.downloads)
    except Exception:
        return None
    if not download_root.exists():
        return None
    seen: set[Path] = set()
    checked = 0
    for pattern in (f"**/{audio_path.stem}.cue", "**/*.cue"):
        for cue in download_root.glob(pattern):
            if cue in seen:
                continue
            seen.add(cue)
            checked += 1
            if checked > 500:
                return None
            try:
                sheet = _read_cue_sheet(cue)
            except Exception:
                continue
            if sheet.audio_file and Path(sheet.audio_file).name != audio_path.name:
                continue
            if cue.stem == audio_path.stem or (sheet.audio_file and Path(sheet.audio_file).name == audio_path.name):
                return cue
    return None


def _parse_year(value: str | None) -> int:
    if not value:
        return 0
    m = re.search(r"\d{4}", str(value))
    return int(m.group(0)) if m else 0


def _track_meta(track: dict[str, Any], album: dict[str, str], cover_data: bytes | None = None) -> MusicMeta:
    return MusicMeta(
        title=track.get("title") or f"Track {track.get('index', 0):02d}",
        artist=track.get("performer") or album.get("performer", ""),
        album=album.get("title", ""),
        album_artist=album.get("performer", ""),
        year=_parse_year(album.get("date")),
        genre=album.get("genre", ""),
        track_number=int(track.get("index") or 0),
        disc_number=1,
        cover_data=cover_data,
        source="cue",
    )


_INVALID = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def _safe_name(text: str) -> str:
    cleaned = _INVALID.sub("_", (text or "").strip())
    return cleaned.rstrip(". ") or "track"


def _output_dir(audio_path: Path, options: dict[str, Any]) -> Path:
    subdir = str(options.get("output_subdir") or "").strip()
    if not subdir:
        return audio_path.parent
    return audio_path.parent / _safe_name(subdir)


def _local_cover(audio_path: Path) -> bytes | None:
    return find_local_cover_data(audio_path.parent) or read_embedded_cover(str(audio_path))


def _copy_album_sidecars(source_audio: Path, cue_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in [cue_path, *source_audio.parent.glob("*.log")]:
        try:
            target = output_dir / path.name
            if path.exists() and path.is_file() and path.resolve() != target.resolve() and not target.exists():
                shutil.copy2(path, target)
        except Exception as exc:
            logger.debug("failed to copy sidecar %s: %s", path, exc)


def _propose(file: MusicFile, options: dict[str, Any]) -> dict[str, Any] | None:
    if not file.file_path:
        return None
    audio_path = Path(file.file_path)
    cue_path = _matched_cue(audio_path) or (audio_path.parent / (audio_path.stem + ".cue"))
    if not cue_path.exists():
        cue_opt = options.get("cue_path")
        cue_path = Path(cue_opt) if cue_opt else cue_path
    if not cue_path or not cue_path.exists():
        return None
    sheet = _read_cue_sheet(cue_path)
    tracks, album_meta = sheet.tracks, sheet.album
    if len(tracks) <= 1:
        return None
    output_dir = _output_dir(audio_path, options)
    return {
        "audio_path": str(audio_path),
        "cue_path": str(cue_path),
        "output_dir": str(output_dir),
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


def preview(db: Session, files: list[MusicFile], options: dict[str, Any]) -> ToolPreview:
    items: list[PreviewItem] = []
    plans = 0
    track_total = 0
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
        tracks = plan["tracks"]
        items.append(PreviewItem(
            file_id=f.id,
            file_path=f.file_path,
            label=Path(f.file_path).name if f.file_path else str(f.id),
            before={"file_path": f.file_path},
            after={"album": plan["album"], "output_dir": plan["output_dir"], "tracks": tracks},
            would_change=True,
            reason=f"计划拆出 {len(tracks)} 首 → {plan['output_dir']}",
        ))
        plans += 1
        track_total += len(tracks)
    return ToolPreview(tool="split_audio", items=items, summary={"changed": plans, "planned": plans, "tracks": track_total, "total": len(items)})


def apply(db: Session, files: list[MusicFile], options: dict[str, Any], on_progress) -> dict:
    if shutil.which("ffmpeg") is None:
        return {"split": 0, "tracks": 0, "total": len(files), "error": "ffmpeg 不可用"}
    keep_original = bool(options.get("keep_original", True))
    overwrite_existing = bool(options.get("overwrite_existing", False))
    split_count = 0
    written_tracks = 0
    failed_tracks = 0
    for idx, f in enumerate(files):
        try:
            plan = _propose(f, options)
            if not plan:
                on_progress(idx, "skip: no cue")
                continue
            audio_path = Path(plan["audio_path"])
            cue_path = Path(plan["cue_path"])
            output_dir = Path(plan["output_dir"])
            output_dir.mkdir(parents=True, exist_ok=True)
            _copy_album_sidecars(audio_path, cue_path, output_dir)
            cover_data = _local_cover(audio_path)
            if cover_data:
                save_cover(str(output_dir), cover_data)
            tracks = plan["tracks"]
            file_success = 0
            for ti, track in enumerate(tracks):
                out_path = Path(track["out"])
                if out_path.exists() and not overwrite_existing:
                    on_progress(idx, f"err:target exists {out_path}")
                    failed_tracks += 1
                    continue
                start = float(track["start_seconds"])
                end = float(tracks[ti + 1]["start_seconds"]) if ti + 1 < len(tracks) else 0.0
                duration = end - start if end > start else 0.0
                args = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.3f}",
                    "-i", str(audio_path),
                ]
                if duration > 0:
                    args.extend(["-t", f"{duration:.3f}"])
                args.extend(["-c", "copy", str(out_path)])
                proc = subprocess.run(args, capture_output=True, text=True)
                if proc.returncode != 0:
                    on_progress(idx, f"err:track {track['index']} ffmpeg failed: {proc.stderr.strip()[:200]}")
                    failed_tracks += 1
                    continue
                meta = _track_meta(track, plan["album"], cover_data=cover_data)
                tag_file(str(out_path), meta)
                audio_meta = read_audio_metadata(str(out_path))
                row = db.query(MusicFile).filter(MusicFile.file_path == str(out_path)).first()
                if not row:
                    row = MusicFile(file_path=str(out_path))
                    db.add(row)
                row.link_path = str(out_path)
                row.format = out_path.suffix.lstrip(".")
                row.scraped = True
                row.artist = meta.artist
                row.album_artist = meta.album_artist or meta.artist
                row.album = meta.album
                row.title = meta.title
                row.year = meta.year
                row.genre = meta.genre
                row.track_number = meta.track_number or None
                row.disc_number = meta.disc_number or None
                row.duration = audio_meta.get("duration")
                row.bitrate = audio_meta.get("bitrate")
                row.sample_rate = audio_meta.get("sample_rate")
                row.channels = audio_meta.get("channels")
                written_tracks += 1
                file_success += 1
            if file_success:
                split_count += 1
            if not keep_original and file_success == len(tracks):
                trash_dir = audio_path.parent / ".originals"
                trash_dir.mkdir(exist_ok=True)
                moved = trash_dir / audio_path.name
                shutil.move(str(audio_path), str(moved))
                f.file_path = str(moved)
                f.link_path = str(moved)
                f.scraped = False
            on_progress(idx, f"split {file_success}/{len(tracks)} tracks")
        except Exception as exc:
            logger.exception("split_audio failed for %s", getattr(f, "file_path", "?"))
            on_progress(idx, f"err:{exc}")
    return {"split": split_count, "tracks": written_tracks, "failed_tracks": failed_tracks, "total": len(files)}
