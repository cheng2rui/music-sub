#!/usr/bin/env python3
"""Real online download E2E flow.

Searches an online source, resolves candidates, downloads one selected song,
verifies library import and stream playback, moves the imported file(s) to
trash, restores them, rescans the library, and optionally cleans the test files.

This script performs a real online download. Use --confirm-download to run.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def request(base: str, path: str, *, method: str = "GET", token: str = "", data: Any = None, timeout: int = 120, raw: bool = False) -> Any:
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
        raise RuntimeError(f"HTTP {exc.code} {path}: {text[:500]}") from exc


def ok(name: str, detail: str = "") -> None:
    print(f"✅ {name}{': ' + detail if detail else ''}")


def poll_job(base: str, token: str, job_id: str, timeout_s: int = 90) -> dict:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = request(base, f"/api/library/jobs/{job_id}", token=token, timeout=30)
        if last.get("status") in {"done", "failed", "cancelled"}:
            return last
        time.sleep(0.8)
    raise RuntimeError(f"job timeout: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8400")
    ap.add_argument("--username", default="888")
    ap.add_argument("--password", default="888")
    ap.add_argument("--keyword", default="丁当 洋葱")
    ap.add_argument("--source", default="qq")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--confirm-download", action="store_true", help="Required: perform a real online download")
    ap.add_argument("--cleanup", action="store_true", help="Move restored test file(s) back to trash and leave no library rows")
    ap.add_argument("--allow-existing", action="store_true", help="Allow testing a song title that already exists in the library")
    args = ap.parse_args()

    if not args.confirm_download:
        raise SystemExit("Refusing to download without --confirm-download")

    login = request(args.base, "/api/auth/login", method="POST", data={"username": args.username, "password": args.password})
    token = login.get("access_token") or login.get("token")
    if not token:
        raise RuntimeError(f"login token missing: {login}")
    ok("login")

    rows = request(args.base, "/api/online/search", method="POST", token=token, data={"keyword": args.keyword, "sources": [args.source], "limit": args.limit}, timeout=120)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"online search returned no rows: {rows}")
    ok("online search", f"{len(rows)} rows source={args.source}")

    chosen = None
    resolved = None
    for row in rows:
        try:
            res = request(args.base, "/api/online/resolve", method="POST", token=token, data={"song": row}, timeout=120)
            print(f"- {row.get('title')}: candidates={res.get('candidate_count')}")
            if res.get("candidate_count", 0) > 0:
                chosen = row
                resolved = res
                break
        except Exception as exc:
            print(f"- {row.get('title')}: resolve failed: {exc}")
    if not chosen:
        raise RuntimeError("no resolvable online result")
    ok("online resolve", f"{chosen.get('title')} candidates={resolved.get('candidate_count')}")

    # Safety guard: by default avoid testing a song that already exists in the
    # library, because online downloads can share the same final target path.
    title_q = urllib.parse.urlencode({"q": chosen.get("title") or "", "limit": 100})
    existing = request(args.base, f"/api/library/files?{title_q}", token=token)
    existing_matches = [f for f in (existing.get("items") or []) if (chosen.get("title") or "") and (chosen.get("title") or "") in (f.get("title") or f.get("file_path") or "")]
    if existing_matches and not args.allow_existing:
        raise RuntimeError(f"library already has title {chosen.get('title')!r}; choose another keyword or pass --allow-existing")

    before_stats = request(args.base, "/api/library/stats", token=token)
    download = request(args.base, "/api/online/download", method="POST", token=token, data={"song": chosen, "organize": True}, timeout=240)
    if not download.get("ok"):
        raise RuntimeError(f"download failed: {download}")
    task_id = download.get("task_id")
    ok("online download + organize", f"task_id={task_id}")

    # Find imported files by task id first, then fallback to title/artist search.
    imported = []
    for _ in range(10):
        files = request(args.base, "/api/library/files?limit=200&sort=track", token=token)
        imported = [f for f in (files.get("items") or []) if f.get("task_id") == task_id]
        if imported:
            break
        title = str(chosen.get("title") or "").lower()
        artist = str(chosen.get("artist") or "").split("/")[0].lower()
        imported = [f for f in (files.get("items") or []) if title and title in str(f.get("title") or f.get("file_path") or "").lower() and (not artist or artist in str(f.get("artist") or f.get("album_artist") or "").lower())]
        if imported:
            break
        time.sleep(0.8)
    if not imported:
        after_stats = request(args.base, "/api/library/stats", token=token)
        raise RuntimeError(f"imported library row not found; before={before_stats} after={after_stats}")
    file_ids = [int(f["id"]) for f in imported]
    ok("library import", f"file_ids={file_ids}")

    stream = request(args.base, f"/api/library/stream/{file_ids[0]}?token={urllib.parse.quote(token)}", raw=True, timeout=60)
    if len(stream) < 4096:
        raise RuntimeError(f"stream too small: {len(stream)}")
    ok("stream playback endpoint", f"{len(stream)} bytes")

    delete = request(args.base, "/api/library/tools/delete_files/apply", method="POST", token=token, data={"file_ids": file_ids, "options": {"delete_files": True, "delete_empty_dirs": True, "delete_missing_db_rows": True, "mode": "trash"}, "async": False}, timeout=120)
    if not delete.get("ok") or int((delete.get("summary") or {}).get("trashed_files") or 0) < 1:
        raise RuntimeError(f"delete-to-trash failed: {delete}")
    ok("delete to trash", json.dumps(delete.get("summary"), ensure_ascii=False))

    trash = request(args.base, "/api/library/trash?limit=500", token=token)
    title = chosen.get("title") or ""
    matches = [x for x in (trash.get("items") or []) if title and title in (x.get("filename") or x.get("relative_path") or "")]
    if not matches:
        raise RuntimeError(f"trashed downloaded file not found for title={title}: {trash}")
    restored_paths = []
    for item in matches[: len(file_ids)]:
        restored = request(args.base, "/api/library/trash/restore", method="POST", token=token, data={"trash_path": item["trash_path"]}, timeout=120)
        if not restored.get("ok"):
            raise RuntimeError(f"restore failed: {restored}")
        restored_paths.append(restored.get("restored_path"))
    ok("restore from trash", f"{len(restored_paths)} files")

    scan = request(args.base, "/api/library/scan", method="POST", token=token, data={"remove_missing": False}, timeout=60)
    job = poll_job(args.base, token, scan.get("job_id"), timeout_s=120)
    if job.get("status") != "done":
        raise RuntimeError(f"scan failed: {job}")
    ok("rescan after restore", scan.get("job_id"))

    if args.cleanup:
        # Re-find only rows created by this download task or rows whose exact
        # restored_path was produced by this run. Never cleanup by title, because
        # a real library may already contain the same song.
        files = request(args.base, "/api/library/files?limit=500&sort=track", token=token)
        restored_set = {p for p in restored_paths if p}
        cleanup_ids = [int(f["id"]) for f in (files.get("items") or []) if f.get("task_id") == task_id or f.get("file_path") in restored_set]
        if cleanup_ids:
            cleanup = request(args.base, "/api/library/tools/delete_files/apply", method="POST", token=token, data={"file_ids": cleanup_ids, "options": {"delete_files": True, "delete_empty_dirs": True, "delete_missing_db_rows": True, "mode": "trash"}, "async": False}, timeout=120)
            ok("cleanup restored test files to trash", json.dumps(cleanup.get("summary"), ensure_ascii=False))
        else:
            ok("cleanup skipped", "no rows with this task_id after restore/rescan")

    print("\nOnline download E2E passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
