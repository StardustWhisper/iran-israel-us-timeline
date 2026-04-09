#!/usr/bin/env python3
"""Call an OpenAI-compatible /chat/completions endpoint on the cpa-plus provider.

Reads:
- base URL from ~/.openclaw/openclaw.json provider "cpa-plus" baseUrl
- API key from env: CPA_PLUS_API_KEY (Bearer)

Usage:
  python3 scripts/cpa_chat_completions.py \
    --model gpt-5.2 \
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
        .get("cpa-plus", {})
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
        raise SystemExit("missing cpa-plus baseUrl in ~/.openclaw/openclaw.json")

    key = os.environ.get("CPA_PLUS_API_KEY", "").strip()
    if not key:
        raise SystemExit("missing CPA_PLUS_API_KEY env")

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

    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    j = json.loads(raw)

    # Treat provider-side errors or empty generations as failures so callers can fallback.
    if isinstance(j, dict) and j.get("error"):
        err = j.get("error")
        raise SystemExit(f"provider_error: {err}")

    choices = j.get("choices") if isinstance(j, dict) else None
    if not choices or not isinstance(choices, list):
        raise SystemExit(f"bad_response_no_choices: {raw[:300]}")

    msg = (choices[0] or {}).get("message", {}) or {}
    content = (msg.get("content") or "").strip()

    # Some providers may return main text in `reasoning_content` with empty `content`.
    if not content:
        rc = (msg.get("reasoning_content") or "").strip()
        if rc:
            import re

            m = re.search(r"(?m)^#\s+\S.*$", rc)
            if m:
                content = rc[m.start() :].strip()
            else:
                content = rc.strip()

    if not content or len(content) < 200:
        raise SystemExit(f"empty_or_too_short_content: {len(content)}")

    # Require the generation to look like a real Markdown article.
    # Our pipeline expects raw drafts to start with a single H1.
    import re

    m = re.search(r"(?m)^#\s+\S.+$", content)
    if m:
        content = content[m.start() :].strip()
    else:
        raise SystemExit("no_h1_title_in_output")

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content + "\n", encoding="utf-8")

    summary = {
        "ok": True,
        "model": args.model,
        "out": str(out_path),
        "chars": len(content),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
