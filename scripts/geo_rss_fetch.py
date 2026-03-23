#!/usr/bin/env python3
"""Fetch articles for a blogwatcher blog into JSON.

Dependency-free parser for `blogwatcher articles` output.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ITEM_RE = re.compile(r"^\s*\[(\d+)\]\s*\[(\w+)\]\s*(.+?)\s*$")
URL_RE = re.compile(r"^\s*URL:\s*(\S+)\s*$")
PUB_RE = re.compile(r"^\s*Published:\s*(\d{4}-\d{2}-\d{2}).*$")


def run(*cmd: str) -> str:
    return subprocess.check_output(list(cmd), text=True, stderr=subprocess.STDOUT)


def parse_articles(text: str) -> list[dict]:
    lines = text.splitlines()
    items: list[dict] = []
    cur: dict | None = None
    for line in lines:
        m = ITEM_RE.match(line)
        if m:
            if cur:
                items.append(cur)
            cur = {
                "id": int(m.group(1)),
                "status": m.group(2),
                "title": m.group(3).strip(),
                "url": None,
                "published": None,
            }
            continue
        if not cur:
            continue
        mu = URL_RE.match(line)
        if mu:
            cur["url"] = mu.group(1)
            continue
        mp = PUB_RE.match(line)
        if mp:
            cur["published"] = mp.group(1)
            continue

    if cur:
        items.append(cur)

    out = []
    for it in items:
        if not it.get("url"):
            continue
        out.append(it)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blog", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--only-new", action="store_true")
    ap.add_argument("--scan", action="store_true")
    args = ap.parse_args()

    if args.scan:
        run("blogwatcher", "scan", args.blog)

    text = run("blogwatcher", "articles", "--all", "--blog", args.blog)
    items = parse_articles(text)
    if args.only_new:
        items = [it for it in items if it.get("status") == "new"]
    items = items[: max(0, args.limit)]

    payload = {
        "blog": args.blog,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": items,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
