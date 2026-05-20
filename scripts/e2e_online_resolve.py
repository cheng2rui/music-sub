#!/usr/bin/env python3
"""Online music search + resolve diagnostic smoke.

This intentionally does not download by default. It verifies the online search
API and the new resolve endpoint so QQ/NKI parse issues can be diagnosed without
creating real music files.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
import urllib.error
from typing import Any


def request(base: str, path: str, *, method: str = "GET", token: str = "", data: Any = None, timeout: int = 60) -> Any:
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
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {raw[:500]}") from exc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8400")
    ap.add_argument("--username", default="888")
    ap.add_argument("--password", default="888")
    ap.add_argument("--keyword", default="丁当 下一站 天后 自选+精选")
    ap.add_argument("--source", default="qq")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    login = request(args.base, "/api/auth/login", method="POST", data={"username": args.username, "password": args.password})
    token = login.get("access_token") or login.get("token")
    if not token:
        raise RuntimeError(f"login token missing: {login}")
    print("✅ login")

    rows = request(args.base, "/api/online/search", method="POST", token=token, data={"keyword": args.keyword, "sources": [args.source], "limit": args.limit}, timeout=90)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"online search returned no rows: {rows}")
    print(f"✅ online search: {len(rows)} rows source={args.source}")

    ok = 0
    failures = []
    for row in rows[: args.limit]:
        title = row.get("title") or row.get("filename") or row.get("song_id")
        try:
            resolved = request(args.base, "/api/online/resolve", method="POST", token=token, data={"song": row}, timeout=120)
            print(f"- {title}: candidates={resolved.get('candidate_count')} {resolved.get('candidates')}")
            if resolved.get("candidate_count", 0) > 0:
                ok += 1
        except Exception as exc:
            failures.append({"title": title, "error": str(exc)[:300]})
            print(f"- {title}: resolve failed: {exc}")
    if ok < 1:
        raise RuntimeError(f"no resolvable rows; failures={failures}")
    print(f"✅ online resolve: {ok}/{min(len(rows), args.limit)} rows resolvable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
