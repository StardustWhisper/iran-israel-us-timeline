#!/usr/bin/env python3
"""Generate a Markdown article by calling `openclaw agent` and write it to a file.

Why: direct /chat/completions calls to some gateways may return null content or
mix meta/planning text. The OpenClaw agent path is more reliable because it
uses the gateway's provider adapter.

This script:
- reads prompt from --message-file (or --message)
- calls: bash scripts/openclaw_cli.sh agent ... --json
- extracts the longest payload text
- enforces the output contains an H1 (# ...)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys


def _extract_text(j: dict) -> str:
    payloads = ((j.get("result") or {}).get("payloads") or []) if isinstance(j, dict) else []
    if not isinstance(payloads, list) or not payloads:
        return ""
    best = max(payloads, key=lambda p: len((p.get("text") or "").strip()))
    return str((best.get("text") or "").strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--to", default="+15555550123")
    ap.add_argument("--message", default="")
    ap.add_argument("--message-file", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    msg = args.message
    if args.message_file:
        msg = pathlib.Path(args.message_file).read_text(encoding="utf-8")

    cmd = [
        "bash",
        str(pathlib.Path("scripts/openclaw_cli.sh")),
        "agent",
        "--agent",
        args.agent,
        "--session-id",
        args.session_id,
        "--to",
        args.to,
        "--timeout",
        str(args.timeout),
        "--json",
        "--message",
        msg,
    ]

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-2000:] + "\n")
        return p.returncode

    # openclaw may print plugin lines; keep last JSON object
    out = p.stdout.strip()
    start = out.find("{")
    if start == -1:
        sys.stderr.write("no_json_output\n")
        return 2
    j = json.loads(out[start:])

    text = _extract_text(j)
    if not text or len(text) < 200:
        raise SystemExit(f"empty_or_too_short_content: {len(text)}")

    m = re.search(r"(?m)^#\s+\S.+$", text)
    if m:
        text = text[m.start() :].strip()
    else:
        raise SystemExit("no_h1_title_in_output")

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "chars": len(text)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
