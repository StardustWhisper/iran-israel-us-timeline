#!/usr/bin/env python3
"""CPA token monitor (hourly poll + optional audit report).

This script combines:
- audit: poll token files and summarize quota/limit status
- cleanup: refresh/delete tokens when specific 401 errors are detected

Behavior (per Lambda):
1) Do NOT scan logs.
2) Every run, poll token files and fetch remaining quota from:
      GET https://chatgpt.com/backend-api/codex/usage
   - If response is OK -> no cleanup action.
   - "余额为 0" is interpreted as the main weekly limit being reached:
        rate_limit.limit_reached == true  OR  rate_limit.primary_window.used_percent >= 100
3) Cleanup rules (only when not in --audit-only mode):
   - 401 + "authentication token has been invalidated" -> refresh token, retry once;
     if still cannot fetch quota -> delete token file.
   - 401 + "account has been deactivated" (or code=account_deactivated) -> delete token file.

Modes:
- default: cleanup mode (may refresh/delete) + prints summary only when actions occurred.
- --audit-only: read-only; never refresh/delete; always prints summary.
- --report / --report-json: print summary even if no actions.
- --dry-run: compute actions but do not refresh/delete.

Exit codes:
  0: no cleanup action taken
  2: refreshed and/or deleted one or more tokens
  1: script error
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import urllib.request
import urllib.error

# Safety constraint: this script only touches token files and codex token files.
# - token_*   (OAuth tokens stored by deploy-cli-proxy)
# - codex*    (future/alternate codex token filenames)
TOKEN_GLOBS = [
    "/home/ubuntu/github/deploy-cli-proxy/auths/token_*.json",
    "/home/ubuntu/github/deploy-cli-proxy/auths/codex*.json",
]
REFRESH_TOKEN_PY = "/home/ubuntu/github/deploy-cli-proxy/backup/refresh_token.py"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"

# Substring match (do NOT include a leading "401 ", backend returns message without it)
INVALIDATED_SUBSTR = "authentication token has been invalidated"
DEACTIVATED_SUBSTR = "account has been deactivated"


def get_window_used_percent(root: Dict[str, Any] | None, field: str) -> float | None:
    """field in {rate_limit, code_review_rate_limit} -> primary_window.used_percent"""
    if not isinstance(root, dict):
        return None
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


def is_main_limit_zero(root: Dict[str, Any] | None) -> bool:
    """主周限额用尽：limit_reached=true 或 used_percent>=100"""
    if not isinstance(root, dict):
        return False
    rl = root.get("rate_limit")
    if isinstance(rl, dict) and rl.get("limit_reached") is True:
        return True
    used = get_window_used_percent(root, "rate_limit")
    return used is not None and used >= 100


@dataclass
class TokenFile:
    path: Path
    email: str | None
    account_id: str | None
    access_token: str | None


@dataclass
class PollResult:
    ok: bool
    status: int | None
    body_text: str
    parsed: Dict[str, Any] | None


def load_token_file(path: Path) -> TokenFile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return TokenFile(path=path, email=None, account_id=None, access_token=None)

    email = (data.get("email") or None)
    account_id = (data.get("account_id") or None)
    access_token = (data.get("access_token") or None)
    if isinstance(email, str):
        email = email.strip() or None
    if isinstance(account_id, str):
        account_id = account_id.strip() or None
    if isinstance(access_token, str):
        access_token = access_token.strip() or None

    return TokenFile(path=path, email=email, account_id=account_id, access_token=access_token)


def _try_parse_json(text: str) -> Dict[str, Any] | None:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def http_get_codex_usage(tf: TokenFile, timeout_s: int = 25) -> PollResult:
    token = (tf.access_token or "").strip()
    if not token:
        return PollResult(ok=False, status=None, body_text="missing access_token", parsed=None)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "MOSS-cpa-token-monitor",
        # Codex CLI headers (helps avoid some backend behavior differences)
        "Originator": "codex_cli_rs",
    }
    if tf.account_id:
        headers["Chatgpt-Account-Id"] = tf.account_id

    req = urllib.request.Request(CODEX_USAGE_URL, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            txt = raw.decode("utf-8", "replace")
            parsed = _try_parse_json(txt)
            return PollResult(ok=(resp.status == 200), status=resp.status, body_text=txt, parsed=parsed)
    except urllib.error.HTTPError as e:
        raw = e.read()
        txt = raw.decode("utf-8", "replace")
        parsed = _try_parse_json(txt)
        return PollResult(ok=False, status=e.code, body_text=txt, parsed=parsed)
    except Exception as e:
        return PollResult(ok=False, status=None, body_text=f"{type(e).__name__}: {e}", parsed=None)


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


def is_deactivated(r: PollResult) -> bool:
    if r.status != 401:
        return False
    code, typ, msg = extract_error(r.parsed)
    hay = "\n".join([x for x in [code or "", typ or "", msg or "", r.body_text or ""] if x]).lower()
    return (code == "account_deactivated") or (DEACTIVATED_SUBSTR in hay)


def is_invalidated(r: PollResult) -> bool:
    if r.status != 401:
        return False
    code, typ, msg = extract_error(r.parsed)
    hay = "\n".join([x for x in [code or "", typ or "", msg or "", r.body_text or ""] if x]).lower()
    # Prefer error.code if present; otherwise rely on message substring.
    return (code == "token_invalidated") or (INVALIDATED_SUBSTR in hay)


def refresh_token_file(path: Path, dry_run: bool) -> Tuple[bool, str]:
    """Refresh a token file in-place using deploy-cli-proxy/backup/refresh_token.py.

    Returns: (success, detail)
    """
    if dry_run:
        return True, "dry-run: refresh skipped"

    if not Path(REFRESH_TOKEN_PY).exists():
        return False, f"refresh script not found: {REFRESH_TOKEN_PY}"

    # Force refresh regardless of expiry, since invalidated token needs refresh now.
    cmd = [sys.executable, REFRESH_TOKEN_PY, str(path), "--force"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if p.returncode == 0:
            return True, "refreshed"
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-3:]
        return False, "refresh failed: " + (" | ".join(tail) if tail else f"rc={p.returncode}")
    except Exception as e:
        return False, f"refresh exception: {type(e).__name__}: {e}"


def delete_token_file(path: Path, dry_run: bool) -> Tuple[bool, str]:
    if dry_run:
        return True, "dry-run: delete skipped"
    try:
        path.unlink(missing_ok=True)
        return True, "deleted"
    except Exception as e:
        return False, f"delete failed: {type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="CPA token monitor (audit + cleanup for token_* and codex* files).")
    ap.add_argument("--dry-run", action="store_true", help="Do not refresh or delete any token files (compute actions only).")
    ap.add_argument("--audit-only", action="store_true", help="Read-only: never refresh/delete; always print a summary.")
    ap.add_argument("--report", action="store_true", help="Always print a summary (even if no actions).")
    ap.add_argument("--report-json", action="store_true", help="Always print JSON summary (even if no actions).")
    ap.add_argument("--limit", type=int, default=0, help="Optional: only process first N token files (0 = all).")
    args = ap.parse_args()

    # Only process token/codex token files.
    files: list[Path] = []
    for g in TOKEN_GLOBS:
        files.extend(Path(p) for p in glob.glob(g))
    files = sorted(set(files), key=lambda x: str(x))

    if args.limit and args.limit > 0:
        files = files[: args.limit]

    if not files:
        if args.report or args.report_json or args.audit_only:
            out = {"scanned": 0, "ok_count": 0, "zero_remaining_count": 0, "error_count": 0, "errors": []}
            if args.report_json:
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            else:
                sys.stdout.write("CPA token poll: scanned=0\n")
        return 0

    # --- audit stats ---
    ok_count = 0
    zero_remaining_count = 0
    err_counter: Counter[tuple[int | None, str | None, str | None]] = Counter()

    # --- cleanup actions ---
    refreshed: list[str] = []
    deleted: list[str] = []
    notes: list[str] = []

    for path in files:
        tf = load_token_file(path)
        label = tf.email or path.name

        r1 = http_get_codex_usage(tf)

        if r1.ok and isinstance(r1.parsed, dict):
            ok_count += 1
            if is_main_limit_zero(r1.parsed):
                zero_remaining_count += 1
            continue

        # audit: count error
        code, typ, _msg = extract_error(r1.parsed)
        err_counter[(r1.status, code, typ)] += 1

        # cleanup: only for targeted 401 cases, and only when not audit-only
        if args.audit_only:
            continue

        # 401 deactivated -> delete immediately
        if is_deactivated(r1):
            ok, detail = delete_token_file(path, args.dry_run)
            if ok:
                deleted.append(label)
            else:
                notes.append(f"{label}: {detail}")
            continue

        # 401 invalidated -> refresh -> retry once -> if still not OK -> delete
        if is_invalidated(r1):
            ok_refresh, refresh_detail = refresh_token_file(path, args.dry_run)
            if ok_refresh:
                refreshed.append(label)
            else:
                ok_del, del_detail = delete_token_file(path, args.dry_run)
                if ok_del:
                    deleted.append(label)
                else:
                    notes.append(f"{label}: refresh failed ({refresh_detail}); delete failed ({del_detail})")
                continue

            tf2 = load_token_file(path)
            r2 = http_get_codex_usage(tf2)
            if r2.ok:
                continue

            ok_del, del_detail = delete_token_file(path, args.dry_run)
            if ok_del:
                deleted.append(label)
            else:
                notes.append(f"{label}: refreshed but still not ok; {del_detail}")
            continue

        # Other errors: ignore for cleanup
        continue

    # --- output ---
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Shanghai")
    except Exception:
        tz = None

    now = datetime.now(tz)
    summary = {
        # Timestamps for downstream automation (default UTC+8)
        "tz": "Asia/Shanghai",
        "ts": now.isoformat(),
        "date": now.date().isoformat(),

        "scanned": len(files),
        "ok_count": ok_count,
        "zero_remaining_count": zero_remaining_count,
        "error_count": sum(err_counter.values()),
        "errors": [
            {"http_status": k[0], "error_code": k[1], "error_type": k[2], "count": v}
            for k, v in sorted(err_counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
        ],
        "actions": {
            "refreshed": len(refreshed),
            "deleted": len(deleted),
            "dry_run": bool(args.dry_run),
            "audit_only": bool(args.audit_only),
        },
        "note": "zero_remaining_count means main weekly limit reached: rate_limit.limit_reached==true OR used_percent>=100",
    }

    did_actions = (len(refreshed) + len(deleted)) > 0 or bool(notes)
    should_print = args.audit_only or args.report or args.report_json or did_actions

    if should_print:
        if args.report_json:
            sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
        else:
            lines: list[str] = []
            header = "CPA token poll"
            if args.audit_only:
                header += " (audit-only)"
            if args.dry_run:
                header += " (dry-run)"
            lines.append(header)
            lines.append(
                f"scanned={summary['scanned']} ok={summary['ok_count']} zero={summary['zero_remaining_count']} errors={summary['error_count']} refreshed={len(refreshed)} deleted={len(deleted)}"
            )

            if summary["errors"]:
                lines.append("errors:")
                for e in summary["errors"][:30]:
                    lines.append(f"- {e['http_status']} {e['error_code']} {e['error_type']} x{e['count']}")

            if refreshed:
                lines.append("refreshed:")
                for x in refreshed[:50]:
                    lines.append(f"- {x}")
                if len(refreshed) > 50:
                    lines.append(f"- ... +{len(refreshed)-50}")

            if deleted:
                lines.append("deleted:")
                for x in deleted[:50]:
                    lines.append(f"- {x}")
                if len(deleted) > 50:
                    lines.append(f"- ... +{len(deleted)-50}")

            if notes:
                lines.append("notes:")
                for x in notes[:50]:
                    lines.append(f"- {x}")
                if len(notes) > 50:
                    lines.append(f"- ... +{len(notes)-50}")

            sys.stdout.write("\n".join(lines) + "\n")

    # Exit code semantics: 2 iff we actually took cleanup actions (or would in dry-run?)
    if args.audit_only:
        return 0
    if (len(refreshed) + len(deleted)) > 0 or bool(notes):
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
