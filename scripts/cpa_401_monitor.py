#!/usr/bin/env python3
"""CPA token monitor (hourly poll).

Replaces the old log-based 401 monitor.

Behavior (per Lambda):
1) Do NOT scan logs.
2) Every run, poll all token files and try to fetch remaining quota.
   - If quota can be fetched successfully -> do nothing.
3) If quota fetch returns:
   - 401 + "Your authentication token has been invalidated. Please try signing in again."
     -> refresh token, retry once; if still cannot fetch quota -> delete token file.
   - 401 + "Your OpenAI account has been deactivated, ..."
     -> delete token file immediately.

Exit codes:
  0: no action needed (all OK)
  2: refreshed and/or deleted one or more tokens (stdout contains summary)
  1: script error

Notes:
- The quota endpoint used for ChatGPT/Codex OAuth tokens is:
    https://chatgpt.com/backend-api/codex/usage
- Safe mode is supported via --dry-run (no writes / no deletes).
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import urllib.request
import urllib.error

TOKEN_GLOB = "/home/ubuntu/github/deploy-cli-proxy/auths/token_*.json"
REFRESH_TOKEN_PY = "/home/ubuntu/github/deploy-cli-proxy/backup/refresh_token.py"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"

# Substring match (do NOT include a leading "401 ", backend returns message without it)
INVALIDATED_SUBSTR = "authentication token has been invalidated"
DEACTIVATED_SUBSTR = "account has been deactivated"


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


def extract_error(parsed: Dict[str, Any] | None) -> Tuple[str | None, str | None]:
    """Return (error_code, error_message) if present."""
    if not isinstance(parsed, dict):
        return None, None
    err = parsed.get("error")
    if not isinstance(err, dict):
        return None, None
    code = err.get("code")
    msg = err.get("message")
    code_s = code.strip() if isinstance(code, str) else None
    msg_s = msg.strip() if isinstance(msg, str) else None
    return code_s or None, msg_s or None


def is_deactivated(r: PollResult) -> bool:
    if r.status != 401:
        return False
    code, msg = extract_error(r.parsed)
    hay = "\n".join([x for x in [code or "", msg or "", r.body_text or ""] if x]).lower()
    return (code == "account_deactivated") or (DEACTIVATED_SUBSTR in hay)


def is_invalidated(r: PollResult) -> bool:
    if r.status != 401:
        return False
    code, msg = extract_error(r.parsed)
    hay = "\n".join([x for x in [code or "", msg or "", r.body_text or ""] if x]).lower()
    # There isn't a stable error.code guaranteed here; rely on message substring.
    return INVALIDATED_SUBSTR in hay


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
    ap = argparse.ArgumentParser(description="CPA token monitor: poll tokens and auto-refresh/delete on 401 errors.")
    ap.add_argument("--dry-run", action="store_true", help="Do not refresh or delete any token files (print what would happen).")
    ap.add_argument("--limit", type=int, default=0, help="Optional: only process first N token files (0 = all).")
    args = ap.parse_args()

    files = [Path(p) for p in sorted(glob.glob(TOKEN_GLOB))]
    if args.limit and args.limit > 0:
        files = files[: args.limit]

    if not files:
        return 0

    refreshed: list[str] = []
    deleted: list[str] = []
    notes: list[str] = []

    for path in files:
        tf = load_token_file(path)
        label = tf.email or path.name

        r1 = http_get_codex_usage(tf)
        if r1.ok:
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

        # Other errors: ignore (per requirement)
        continue

    if not refreshed and not deleted and not notes:
        return 0

    lines: list[str] = []
    header = "CPA token poll: actions detected"
    if args.dry_run:
        header += " (dry-run)"
    lines.append(header)
    lines.append(f"scanned={len(files)} refreshed={len(refreshed)} deleted={len(deleted)}")

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
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(1)
