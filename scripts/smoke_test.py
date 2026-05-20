#!/usr/bin/env python3
"""Music Sub release smoke test.

Covers the minimum gates used before tagging a release:
- health/version
- auth login
- library stats
- album completion conservative dry-run
- notification status
- trash listing
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def request(base: str, path: str, *, method: str = "GET", token: str = "", data: Any = None, timeout: int = 20) -> Any:
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
            raw = resp.read().decode("utf-8", errors="replace")
            ctype = resp.headers.get("content-type", "")
            if "json" in ctype or raw[:1] in "[{":
                return json.loads(raw or "{}")
            return raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {raw[:300]}") from exc


def ok(name: str, detail: str = "") -> None:
    print(f"✅ {name}{': ' + detail if detail else ''}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8400")
    ap.add_argument("--username", default="888")
    ap.add_argument("--password", default="888")
    ap.add_argument("--expect-version", default="")
    ap.add_argument("--container", default="music-sub", help="Docker container name to validate; empty to skip")
    ap.add_argument("--album-artist", default="蔡依林")
    ap.add_argument("--album", default="Ugly Beauty")
    args = ap.parse_args()

    health = request(args.base, "/api/health")
    version = health.get("version")
    if health.get("status") != "ok":
        raise RuntimeError(f"health not ok: {health}")
    if args.expect_version and version != args.expect_version:
        raise RuntimeError(f"version mismatch: expected {args.expect_version}, got {version}")
    ok("health", f"version={version}")

    login = request(args.base, "/api/auth/login", method="POST", data={"username": args.username, "password": args.password})
    token = login.get("access_token") or login.get("token")
    if not token:
        raise RuntimeError(f"login token missing: {login}")
    ok("login")

    stats = request(args.base, "/api/library/stats", token=token)
    if int(stats.get("total_files") or 0) < 0:
        raise RuntimeError(f"bad stats: {stats}")
    ok("library stats", f"files={stats.get('total_files')} unscraped={stats.get('unscraped')}")

    complete = request(args.base, "/api/library/album-complete", method="POST", token=token, data={"artist": args.album_artist, "album": args.album, "dry_run": True, "limit": 10})
    if not complete.get("ok"):
        raise RuntimeError(f"album complete dry-run failed: {complete}")
    candidates = complete.get("candidates") or []
    candidate_ids = [c.get("candidate_id") for c in candidates]
    if len([x for x in candidate_ids if x]) != len(set(x for x in candidate_ids if x)):
        raise RuntimeError(f"album completion candidate_id is not unique: {candidate_ids}")
    for c in candidates:
        if "confidence" not in c or "confidence_label" not in c or "recommended" not in c:
            raise RuntimeError(f"candidate confidence fields missing: {c}")
    ok("album-complete dry-run", f"existing={complete.get('existing')} candidates={len(candidates)}")

    undo_probe = request(args.base, "/api/library/album-complete/undo", method="POST", token=token, data={"file_ids": [999999999], "dry_run": True})
    if not undo_probe.get("ok") or undo_probe.get("matched") != 0:
        raise RuntimeError(f"album complete undo dry-run probe failed: {undo_probe}")
    ok("album-complete undo dry-run", "no-match safe")

    notify = request(args.base, "/api/notify/status", token=token)
    channels = sorted((notify.get("channels") or {}).keys())
    for expected in ["telegram", "wecom", "qqbot", "wechatbot"]:
        if expected not in channels:
            raise RuntimeError(f"notify channel missing: {expected}, got {channels}")
    ok("notify status", ",".join(channels))

    trash = request(args.base, "/api/library/trash?limit=5", token=token)
    if "items" not in trash:
        raise RuntimeError(f"trash listing failed: {trash}")
    ok("trash listing", f"total={trash.get('total')}")

    if args.container:
        create_cmd = """from pathlib import Path
from app.config import config
root = Path(config.paths.library)
trash = root / '.trash' / '20990101' / 'Smoke Artist' / 'Smoke Album' / '01 Smoke Restore.txt'
trash.parent.mkdir(parents=True, exist_ok=True)
trash.write_text('music-sub-smoke-restore\\n', encoding='utf-8')
print(str(trash))
"""
        trash_path = subprocess.check_output(["docker", "exec", args.container, "python", "-c", create_cmd], text=True, timeout=20).strip()
        preview = request(args.base, "/api/library/trash/restore", method="POST", token=token, data={"trash_path": trash_path, "dry_run": True})
        if not preview.get("dry_run") or not str(preview.get("restored_path") or "").endswith("Smoke Artist/Smoke Album/01 Smoke Restore.txt"):
            raise RuntimeError(f"trash restore dry-run bad response: {preview}")
        restored = request(args.base, "/api/library/trash/restore", method="POST", token=token, data={"trash_path": trash_path})
        if not restored.get("ok"):
            raise RuntimeError(f"trash restore smoke failed: {restored}")
        cleanup_cmd = """from pathlib import Path
from app.config import config
root = Path(config.paths.library)
p = root / 'Smoke Artist' / 'Smoke Album' / '01 Smoke Restore.txt'
if p.exists() and p.read_text(encoding='utf-8') == 'music-sub-smoke-restore\\n':
    p.unlink()
for d in [p.parent, p.parent.parent, root / '.trash' / '20990101' / 'Smoke Artist' / 'Smoke Album', root / '.trash' / '20990101' / 'Smoke Artist', root / '.trash' / '20990101']:
    try:
        d.rmdir()
    except Exception:
        pass
"""
        subprocess.check_call(["docker", "exec", args.container, "python", "-c", cleanup_cmd], timeout=20)
        ok("trash restore smoke", "synthetic file restored and cleaned")

        conflict_cmd = """from pathlib import Path
from app.config import config
root = Path(config.paths.library)
target = root / 'Smoke Artist' / 'Smoke Album' / '01 Smoke Conflict.txt'
trash = root / '.trash' / '20990102' / 'Smoke Artist' / 'Smoke Album' / '01 Smoke Conflict.txt'
target.parent.mkdir(parents=True, exist_ok=True)
trash.parent.mkdir(parents=True, exist_ok=True)
target.write_text('existing-target\\n', encoding='utf-8')
trash.write_text('restored-from-trash\\n', encoding='utf-8')
print(str(trash))
"""
        conflict_trash_path = subprocess.check_output(["docker", "exec", args.container, "python", "-c", conflict_cmd], text=True, timeout=20).strip()
        conflict_preview = request(args.base, "/api/library/trash/restore", method="POST", token=token, data={"trash_path": conflict_trash_path, "overwrite": True, "dry_run": True})
        if not conflict_preview.get("would_backup_path"):
            raise RuntimeError(f"trash overwrite dry-run did not report backup path: {conflict_preview}")
        conflict_restored = request(args.base, "/api/library/trash/restore", method="POST", token=token, data={"trash_path": conflict_trash_path, "overwrite": True})
        backup_path = conflict_restored.get("backup_path")
        if not backup_path:
            raise RuntimeError(f"trash overwrite restore did not preserve backup: {conflict_restored}")
        verify_conflict_cmd = f"""from pathlib import Path
from app.config import config
root = Path(config.paths.library)
target = root / 'Smoke Artist' / 'Smoke Album' / '01 Smoke Conflict.txt'
backup = Path({backup_path!r})
assert target.read_text(encoding='utf-8') == 'restored-from-trash\\n'
assert backup.read_text(encoding='utf-8') == 'existing-target\\n'
target.unlink()
backup.unlink()
for d in [target.parent, target.parent.parent, backup.parent, backup.parent.parent, backup.parent.parent.parent, root / '.trash' / '20990102' / 'Smoke Artist' / 'Smoke Album', root / '.trash' / '20990102' / 'Smoke Artist', root / '.trash' / '20990102']:
    try:
        d.rmdir()
    except Exception:
        pass
"""
        subprocess.check_call(["docker", "exec", args.container, "python", "-c", verify_conflict_cmd], timeout=20)
        ok("trash overwrite safety", "existing target preserved in .trash/restore-conflicts")

    restore_many_error = False
    try:
        request(args.base, "/api/library/trash/restore_many", method="POST", token=token, data={"trash_paths": []})
    except RuntimeError as exc:
        restore_many_error = "HTTP 400" in str(exc)
    if not restore_many_error:
        raise RuntimeError("trash restore_many empty payload should return HTTP 400")
    ok("trash restore_many guard")

    if args.expect_version:
        required_assets = [
            "/animal-island/README.md",
            "/animal-island/animal_icon.svg",
            "/animal-island/content_bg_pc.jpg",
            "/animal-island/guide-bg-line.webp",
            "/animal-island/home_bg.svg",
            "/animal-island/menu_bg.svg",
            "/animal-island/components/cursor-icon.png",
            "/animal-island/components/divider_line.png",
            "/animal-island/nook-phone/AppIcons.svg",
            "/animal-island/nook-phone/Property-Camera.svg",
            "/animal-island/nook-phone/Property-Chat.svg",
            "/animal-island/nook-phone/Property-Helicopter.svg",
            "/animal-island/nook-phone/Property-Recipes.svg",
            "/animal-island/nook-phone/Property-Shopping.svg",
            "/animal-island/nook-phone/nook1.svg",
            "/animal-island/nook-phone/nook2.svg",
        ]
        for asset_url in required_assets:
            asset_bytes = request(args.base, asset_url, timeout=20)
            if not asset_bytes:
                raise RuntimeError(f"empty animal island asset: {asset_url}")
        ok("animal island assets", f"{len(required_assets)} files")

        html = request(args.base, "/", timeout=20)
        match = re.search(r'/(assets/index-[^"\']+\.js)', str(html))
        if not match:
            raise RuntimeError("frontend index asset not found in /")
        asset_path = "/" + match.group(1)
        asset = request(args.base, asset_path, timeout=20)
        asset_text = str(asset)
        if args.expect_version not in asset_text:
            raise RuntimeError(f"frontend asset {asset_path} does not contain version {args.expect_version}")
        ok("frontend asset version", asset_path)

        frontend_paths = sorted(set(
            re.findall(r'/(assets/[^"\']+\.(?:js|css))', str(html)) + [asset_path.lstrip("/")]
        ))
        island_ref_asset = ""
        for rel_path in frontend_paths:
            frontend_text = str(request(args.base, "/" + rel_path, timeout=20))
            if "/animal-island/" in frontend_text:
                island_ref_asset = "/" + rel_path
                break
        if not island_ref_asset:
            raise RuntimeError("frontend JS/CSS assets do not reference animal island assets")
        ok("frontend island references", island_ref_asset)

    if args.container and args.expect_version:
        try:
            image = subprocess.check_output(["docker", "inspect", "--format", "{{.Config.Image}}", args.container], text=True, timeout=20).strip()
        except Exception as exc:
            raise RuntimeError(f"docker inspect failed for {args.container}: {exc}") from exc
        if args.expect_version not in image:
            raise RuntimeError(f"container image mismatch: expected {args.expect_version} in {image}")
        ok("docker image", image)

    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"❌ smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
