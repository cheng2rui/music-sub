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
    ok("album-complete dry-run", f"existing={complete.get('existing')} candidates={len(complete.get('candidates') or [])}")

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

    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"❌ smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
