#!/usr/bin/env python3
"""Call an OpenAI-compatible /chat/completions endpoint and return content.

Designed for Grok2API (xai.lambda.xin/v1) where OpenClaw agent session path
may inject large prompts / streaming behavior that some models dislike.

Reads:
- base URL from ~/.openclaw/openclaw.json provider "grok2api" baseUrl
- API key from env: GROK2API_API_KEY (Bearer)

Usage:
  python3 scripts/grok2api_chat_completions.py \
    --model grok-4.20-beta \
    --system "..." \
    --user-file /path/to/prompt.txt \
    --out /path/to/out.md \
    --temperature 0.7 --max-tokens 2400

Outputs:
- Writes assistant message content to --out
- Prints a short JSON summary to stdout
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import urllib.request


def load_base_url() -> str:
    cfg_path = pathlib.Path(os.path.expanduser("~/.openclaw/openclaw.json"))
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = (
        (cfg.get("models", {}).get("providers", {}) or {})
        .get("grok2api", {})
        .get("baseUrl", "")
    )
    return str(base).rstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--system", default="You are a helpful assistant.")
    ap.add_argument("--user", default="")
    ap.add_argument("--user-file", default="")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=2400)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    user = args.user
    if args.user_file:
        user = pathlib.Path(args.user_file).read_text(encoding="utf-8")

    base = load_base_url()
    if not base:
        raise SystemExit("missing grok2api baseUrl in ~/.openclaw/openclaw.json")

    key = os.environ.get("GROK2API_API_KEY", "").strip()
    if not key:
        raise SystemExit("missing GROK2API_API_KEY env")

    url = base + "/chat/completions"
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": args.system},
            {"role": "user", "content": user},
        ],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": False,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)

    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    j = json.loads(raw)
    content = (
        (j.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
    )

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(str(content).strip() + "\n", encoding="utf-8")

    summary = {
        "ok": True,
        "model": args.model,
        "out": str(out_path),
        "chars": len(str(content)),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
