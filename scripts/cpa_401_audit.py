#!/usr/bin/env python3
"""Audit Codex token files: poll remaining usage/quota and summarize.

This script is READ-ONLY: it will NOT refresh or delete tokens.

It checks the same Codex endpoint used by the cleanup script:
  GET https://chatgpt.com/backend-api/codex/usage

Outputs:
- ok_count: tokens that returned 200 with parseable JSON
- remaining(主周限额): derived from rate_limit.primary_window.used_percent
  (remaining_percent = 100 - used_percent)
- remaining(代码审查周限额): derived from code_review_rate_limit.primary_window.used_percent
- "余额为 0" (主周限额) means rate_limit.limit_reached == true OR used_percent >= 100

Error breakdown groups by (http_status, error.code, error.type).

Rationale:
- /codex/usage does not return a single unified numeric "balance". It returns rate-limit windows with
  used_percent + reset time. We therefore treat "剩余" as remaining_percent per window.
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import urllib.request
import urllib.error

CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"
TOKEN_GLOBS = [
    "/home/ubuntu/github/deploy-cli-proxy/auths/token_*.json",
    "/home/ubuntu/github/deploy-cli-proxy/auths/codex*.json",
]


@dataclass
class TokenFile:
    path: Path
    email: str | None
    account_id: str | None
    access_token: str | None


def load_token_file(path: Path) -> TokenFile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return TokenFile(path=path, email=None, account_id=None, access_token=None)

    def norm(v: Any) -> str | None:
        return v.strip() or None if isinstance(v, str) else None

    return TokenFile(
        path=path,
        email=norm(data.get("email")),
        account_id=norm(data.get("account_id")),
        access_token=norm(data.get("access_token")),
    )


def try_parse_json(text: str) -> Dict[str, Any] | None:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def extract_error(parsed: Dict[str, Any] | None) -> Tuple[str | None, str | None, str | None]:
    """Return (error_code, error_type, error_message) if present."""
    if not isinstance(parsed, dict):
        return None, None, None
    err = parsed.get("error")
    if not isinstance(err, dict):
        return None, None, None
    code = err.get("code")
    typ = err.get("type")
    msg = err.get("message")
    code_s = code.strip() if isinstance(code, str) else None
    typ_s = typ.strip() if isinstance(typ, str) else None
    msg_s = msg.strip() if isinstance(msg, str) else None
    return code_s or None, typ_s or None, msg_s or None


def get_window_used_percent(root: Dict[str, Any], field: str) -> float | None:
    """field in {rate_limit, code_review_rate_limit} -> primary_window.used_percent"""
    block = root.get(field)
    if not isinstance(block, dict):
        return None
    pw = block.get("primary_window")
    if not isinstance(pw, dict):
        return None
    v = pw.get("used_percent")
    if isinstance(v, (int, float)):
        return float(v)
    return None


def is_zero_remaining(root: Dict[str, Any]) -> bool:
    """主周限额用尽：limit_reached=true 或 used_percent>=100"""
    rl = root.get("rate_limit")
    if isinstance(rl, dict) and rl.get("limit_reached") is True:
        return True
    used = get_window_used_percent(root, "rate_limit")
    return used is not None and used >= 100


def http_get_codex_usage(tf: TokenFile, timeout_s: int = 25) -> tuple[int | None, str, Dict[str, Any] | None]:
    token = (tf.access_token or "").strip()
    if not token:
        return None, "missing access_token", None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "MOSS-cpa-token-audit",
        "Originator": "codex_cli_rs",
    }
    if tf.account_id:
        headers["Chatgpt-Account-Id"] = tf.account_id

    req = urllib.request.Request(CODEX_USAGE_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            txt = raw.decode("utf-8", "replace")
            return resp.status, txt, try_parse_json(txt)
    except urllib.error.HTTPError as e:
        raw = e.read()
        txt = raw.decode("utf-8", "replace")
        return e.code, txt, try_parse_json(txt)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    files: list[Path] = []
    for g in TOKEN_GLOBS:
        files.extend(Path(p) for p in glob.glob(g))
    files = sorted(set(files), key=lambda x: str(x))
    if args.limit and args.limit > 0:
        files = files[: args.limit]

    ok = 0
    zero = 0
    errors = Counter()

    for path in files:
        tf = load_token_file(path)
        status, body, parsed = http_get_codex_usage(tf)

        if status == 200 and isinstance(parsed, dict):
            ok += 1
            if is_zero_remaining(parsed):
                zero += 1
            continue

        code, typ, _msg = extract_error(parsed)
        errors[(status, code, typ)] += 1

    print(json.dumps({
        "scanned": len(files),
        "ok_count": ok,
        "zero_remaining_count": zero,
        "error_count": sum(errors.values()),
        "errors": [
            {"http_status": k[0], "error_code": k[1], "error_type": k[2], "count": v}
            for k, v in sorted(errors.items(), key=lambda kv: (-kv[1], str(kv[0])))
        ],
        "note": "zero_remaining_count means main weekly limit reached: rate_limit.limit_reached==true OR used_percent>=100",
    }, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
