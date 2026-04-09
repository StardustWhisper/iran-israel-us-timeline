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
import urllib.error


def _post_json(url: str, payload: dict, key: str, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _extract_text_from_chat_completions(j: dict) -> str:
    if isinstance(j, dict) and j.get("error"):
        raise SystemExit(f"provider_error: {j.get('error')}")

    choices = j.get("choices") if isinstance(j, dict) else None
    if not choices or not isinstance(choices, list):
        raise SystemExit("bad_response_no_choices")

    msg = (choices[0] or {}).get("message") or {}
    if not isinstance(msg, dict):
        msg = {}

    content = msg.get("content")
    if content is None:
        content = ""
    content = str(content).strip()

    if not content:
        rc = msg.get("reasoning_content")
        if rc is None:
            rc = ""
        rc = str(rc).strip()
        if rc:
            content = rc

    if not content:
        ot = msg.get("output_text") or msg.get("output")
        if ot:
            content = str(ot).strip()

    return content


def _extract_text_from_responses(j: dict) -> str:
    if isinstance(j, dict) and j.get("error"):
        raise SystemExit(f"provider_error: {j.get('error')}")

    out = j.get("output") if isinstance(j, dict) else None
    if isinstance(out, list):
        for item in out:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                txt = c.get("text") or c.get("output_text")
                if txt:
                    return str(txt).strip()

    if isinstance(j, dict) and j.get("output_text"):
        return str(j.get("output_text")).strip()

    return ""


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

    content = ""

    # 1) chat/completions
    chat_url = base + "/chat/completions"
    chat_payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": args.system},
            {"role": "user", "content": user},
        ],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": False,
    }

    try:
        j = _post_json(chat_url, chat_payload, key)
        content = _extract_text_from_chat_completions(j)
    except urllib.error.HTTPError as e:
        # If chat endpoint is blocked/unsupported, try /responses.
        if e.code not in (404, 405):
            raise
    except Exception:
        pass

    # 2) responses (fallback)
    if not content:
        resp_url = base + "/responses"
        resp_payload = {
            "model": args.model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": args.system}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user}],
                },
            ],
            "temperature": args.temperature,
            "max_output_tokens": args.max_tokens,
        }
        j2 = _post_json(resp_url, resp_payload, key)
        content = _extract_text_from_responses(j2)

    content = (content or "").strip()
    if not content or len(content) < 200:
        raise SystemExit(f"empty_or_too_short_content: {len(content)}")

    # Require the generation to look like a real Markdown article.
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
