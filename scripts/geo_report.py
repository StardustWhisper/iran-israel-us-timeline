#!/usr/bin/env python3
"""Generate geo/econ daily markdown report.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--date", required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    top = data.get("top") or {}
    items = data.get("topN") or []

    lines = []
    lines.append(f"# Geo/Econ Daily Brief — {args.date}")
    lines.append("")
    lines.append(f"Generated at: {data.get('generatedAt')}")
    lines.append("")

    if top:
        lines.append("## Top Story")
        lines.append(f"- **{top.get('title','').strip()}**")
        lines.append(f"  - URL: {top.get('url','')}")
        if top.get("sourceBlog") or top.get("source"):
            lines.append(f"  - Source: {top.get('sourceBlog') or top.get('source')}")
        lines.append(f"  - Score: {top.get('score')}")
        lines.append("")

    lines.append("## Top List")
    for i, it in enumerate(items, 1):
        title = (it.get("title") or "").strip()
        url = it.get("url") or ""
        source = it.get("sourceBlog") or it.get("source") or ""
        score = it.get("score")
        lines.append(f"{i}. {title}")
        if source:
            lines.append(f"   - Source: {source}")
        lines.append(f"   - URL: {url}")
        lines.append(f"   - Score: {score}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
