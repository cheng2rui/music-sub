#!/usr/bin/env python3
"""Smoke test album folder ownership for multi-artist albums.

Runs inside the Music Sub container (or any environment with app imports). It
creates two synthetic tracks from different artists but the same album and checks
that both land in the first/primary album artist folder.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from app.config import config
from app.db import SessionLocal
from app.models import DownloadTask, LibraryAuditEvent, MusicFile
from app.services.pipeline import _process_completed_torrent


def main() -> int:
    artist1 = "Music Sub Split A"
    artist2 = "Music Sub Split B"
    album = "Music Sub Split Album Smoke"
    title1 = "Split Track One"
    title2 = "Split Track Two"
    root = Path(config.paths.downloads) / "split-smoke"
    root.mkdir(parents=True, exist_ok=True)
    task_ids: list[int] = []
    try:
        for idx, (artist, title) in enumerate([(artist1, title1), (artist2, title2)], 1):
            source_dir = root / f"{idx}-{artist}"
            source_dir.mkdir(parents=True, exist_ok=True)
            source = source_dir / f"{idx:02d}.wav"
            subprocess.check_call([
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={440 + idx * 40}:duration=1",
                "-metadata", f"title={title}", "-metadata", f"artist={artist}", "-metadata", f"album={album}", str(source),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            hashv = "split:" + uuid.uuid4().hex[:24]
            db = SessionLocal()
            try:
                task = DownloadTask(torrent_name=title, torrent_hash=hashv, site="split-smoke", size=source.stat().st_size, status="downloaded", save_path=str(source))
                db.add(task)
                db.commit()
                task_ids.append(task.id)
            finally:
                db.close()
            _process_completed_torrent({
                "hash": hashv,
                "name": title,
                "content_path": str(source),
                "metadata": {"title": title, "artist": artist, "album": album, "duration": 1},
                "mark_processed": False,
            })

        db = SessionLocal()
        try:
            rows = db.query(MusicFile).filter(MusicFile.album == album).order_by(MusicFile.id).all()
            folders = sorted({str(Path(r.file_path).parent) for r in rows})
            artists = [(r.artist, r.album_artist, Path(r.file_path).parent.parent.name) for r in rows]
            if len(rows) != 2:
                raise RuntimeError(f"expected 2 rows, got {len(rows)}: {rows}")
            if len(folders) != 1:
                raise RuntimeError(f"album split into multiple folders: {folders}; artists={artists}")
            if Path(folders[0]).parent.name != artist1:
                raise RuntimeError(f"album folder owner should be first artist {artist1!r}, got {folders[0]}")
            print(f"✅ album identity: 2 artists share folder {folders[0]}")
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            rows = db.query(MusicFile).filter(MusicFile.album == album).all()
            for row in rows:
                if row.file_path and Path(row.file_path).exists():
                    try:
                        Path(row.file_path).unlink()
                    except Exception:
                        pass
                db.delete(row)
            if task_ids:
                db.query(DownloadTask).filter(DownloadTask.id.in_(task_ids)).delete(synchronize_session=False)
            like = f"%{album}%"
            db.query(LibraryAuditEvent).filter(
                (LibraryAuditEvent.file_path.like(like)) |
                (LibraryAuditEvent.trash_path.like(like)) |
                (LibraryAuditEvent.restore_path.like(like))
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
        shutil.rmtree(Path(config.paths.library) / artist1 / album, ignore_errors=True)
        shutil.rmtree(Path(config.paths.library) / artist2 / album, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)
        for p in [Path(config.paths.library) / artist1, Path(config.paths.library) / artist2]:
            try:
                p.rmdir()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
