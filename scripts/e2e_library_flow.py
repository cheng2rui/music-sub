#!/usr/bin/env python3
"""Safe end-to-end library flow exercise for Music Sub."""
from __future__ import annotations

import argparse, json, subprocess, time, urllib.error, urllib.parse, urllib.request
from typing import Any


def request(base: str, path: str, *, method: str = "GET", token: str = "", data: Any = None, timeout: int = 30, raw: bool = False) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base.rstrip("/") + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            if raw:
                return payload
            text = payload.decode("utf-8", errors="replace")
            if "json" in resp.headers.get("content-type", "") or text[:1] in "[{":
                return json.loads(text or "{}")
            return text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {text[:300]}") from exc


def ok(name: str, detail: str = "") -> None:
    print(f"✅ {name}{': ' + detail if detail else ''}")


def docker_exec(container: str, code: str, timeout: int = 120) -> str:
    return subprocess.check_output(["docker", "exec", container, "python", "-c", code], text=True, timeout=timeout).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8400")
    ap.add_argument("--username", default="888")
    ap.add_argument("--password", default="888")
    ap.add_argument("--container", default="music-sub")
    ap.add_argument("--keep-artifacts", action="store_true")
    args = ap.parse_args()

    stamp = str(int(time.time()))
    artist = "Music Sub E2E Artist"
    album = f"Music Sub E2E Album {stamp}"
    title = "Music Sub E2E Track"

    login = request(args.base, "/api/auth/login", method="POST", data={"username": args.username, "password": args.password})
    token = login.get("access_token") or login.get("token")
    if not token:
        raise RuntimeError(f"login token missing: {login}")
    ok("login")

    create_code = f'''
import subprocess, uuid
from pathlib import Path
from app.config import config
from app.db import SessionLocal
from app.models import DownloadTask
from app.services.pipeline import _process_completed_torrent
artist={artist!r}; album={album!r}; title={title!r}
source_dir = Path(config.paths.downloads) / 'e2e' / album
source_dir.mkdir(parents=True, exist_ok=True)
source = source_dir / '01-e2e.wav'
subprocess.check_call(['ffmpeg','-y','-f','lavfi','-i','sine=frequency=440:duration=1','-metadata',f'title={{title}}','-metadata',f'artist={{artist}}','-metadata',f'album={{album}}',str(source)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
hashv='e2e:'+uuid.uuid4().hex[:24]
db=SessionLocal()
try:
    task=DownloadTask(torrent_name=title, torrent_hash=hashv, site='e2e', size=source.stat().st_size, status='downloaded', save_path=str(source))
    db.add(task); db.commit(); tid=task.id
finally:
    db.close()
_process_completed_torrent({{'hash': hashv, 'name': title, 'content_path': str(source), 'metadata': {{'title': title, 'artist': artist, 'album_artist': artist, 'album': album, 'duration': 1}}, 'mark_processed': False}})
print(tid)
'''
    task_id = int(docker_exec(args.container, create_code, timeout=180).splitlines()[-1])
    ok("pipeline processed synthetic download", f"task_id={task_id}")

    qs = urllib.parse.urlencode({"album_artist": artist, "album_name": album, "limit": 10})
    files = request(args.base, f"/api/library/files?{qs}", token=token)
    items = files.get("items") or []
    if not items:
        raise RuntimeError(f"processed file not found in library: {files}")
    file_id = items[0]["id"]
    ok("library entry", f"file_id={file_id}")

    stream = request(args.base, f"/api/library/stream/{file_id}?token={urllib.parse.quote(token)}", raw=True, timeout=30)
    if len(stream) < 100:
        raise RuntimeError("stream response too small")
    ok("stream playback endpoint", f"{len(stream)} bytes")

    deleted = request(args.base, "/api/library/tools/delete_files/apply", method="POST", token=token, data={"file_ids": [file_id], "options": {"delete_files": True, "delete_empty_dirs": True, "delete_missing_db_rows": True, "mode": "trash"}, "async": False})
    if not deleted.get("ok") or int((deleted.get("summary") or {}).get("trashed_files") or 0) < 1:
        raise RuntimeError(f"delete-to-trash failed: {deleted}")
    ok("delete to trash", json.dumps(deleted.get("summary"), ensure_ascii=False))

    trash = request(args.base, "/api/library/trash?limit=300", token=token)
    match = next((x for x in (trash.get("items") or []) if album in str(x.get("trash_path") or x.get("relative_path") or "")), None)
    if not match:
        raise RuntimeError(f"trashed synthetic file not found: {trash}")
    restored = request(args.base, "/api/library/trash/restore", method="POST", token=token, data={"trash_path": match["trash_path"]})
    if not restored.get("ok"):
        raise RuntimeError(f"restore failed: {restored}")
    ok("restore from trash")

    scan = request(args.base, "/api/library/scan", method="POST", token=token, data={"remove_missing": False})
    job_id = scan.get("job_id")
    if not job_id:
        raise RuntimeError(f"scan did not start: {scan}")
    job = {}
    for _ in range(50):
        job = request(args.base, f"/api/library/jobs/{job_id}", token=token)
        if job.get("status") in {"done", "failed"}:
            break
        time.sleep(0.5)
    if job.get("status") != "done":
        raise RuntimeError(f"scan did not finish cleanly: {job}")
    ok("rescan after restore", f"job={job_id}")

    restored_files = request(args.base, f"/api/library/files?{qs}", token=token)
    if not (restored_files.get("items") or []):
        raise RuntimeError(f"restored file was not re-imported: {restored_files}")
    ok("restored library entry re-imported")

    audit = request(args.base, "/api/library/audit?limit=50", token=token)
    audit_text = json.dumps(audit, ensure_ascii=False)
    if album not in audit_text or "restore" not in audit_text or "trash" not in audit_text:
        raise RuntimeError(f"audit missing e2e trash/restore records: {audit}")
    ok("audit records")

    if not args.keep_artifacts:
        cleanup_code = f'''
import shutil
from pathlib import Path
from app.config import config
from app.db import SessionLocal
from app.models import DownloadTask, LibraryAuditEvent, MusicFile
artist={artist!r}; album={album!r}
db=SessionLocal()
try:
    rows=db.query(MusicFile).filter(MusicFile.album_artist==artist, MusicFile.album==album).all()
    for row in rows:
        if row.file_path and Path(row.file_path).exists():
            try: Path(row.file_path).unlink()
            except Exception: pass
        db.delete(row)
    db.query(DownloadTask).filter(DownloadTask.id=={task_id}).delete(synchronize_session=False)
    like=f'%{{album}}%'
    db.query(LibraryAuditEvent).filter((LibraryAuditEvent.file_path.like(like)) | (LibraryAuditEvent.trash_path.like(like)) | (LibraryAuditEvent.restore_path.like(like))).delete(synchronize_session=False)
    db.commit()
finally:
    db.close()
for root in [Path(config.paths.library)/artist/album, Path(config.paths.downloads)/'e2e'/album]:
    shutil.rmtree(root, ignore_errors=True)
for root in [Path(config.paths.library)/artist, Path(config.paths.downloads)/'e2e']:
    try: root.rmdir()
    except Exception: pass
'''
        docker_exec(args.container, cleanup_code, timeout=60)
        ok("cleanup synthetic artifacts")

    print("\nE2E library flow passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"❌ e2e failed: {exc}")
        raise SystemExit(1)
