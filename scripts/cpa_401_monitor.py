#!/usr/bin/env python3
"""Monitor CLIProxyAPIPlus error logs for HTTP 401 responses.

- Scans deploy-cli-proxy/logs/error-*.log for new files since last run.
- Extracts a small, non-sensitive summary (timestamp/url/status/error.message).
- Writes state to workspace/memory/cpa_401_monitor_state.json.

Exit codes:
  0: no new 401 found
  2: found one or more 401 (stdout contains alert text)
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path("/home/ubuntu/github/deploy-cli-proxy/logs")
STATE_PATH = Path("/home/ubuntu/.openclaw/workspace/memory/cpa_401_monitor_state.json")
GLOB = "error-*.log"

STATUS_RE = re.compile(r"^Status:\s*(\d+)")
URL_RE = re.compile(r"^URL:\s*(\S+)")
TS_RE = re.compile(r"^Timestamp:\s*(.+)")
# JSON error line in section "=== API RESPONSE ===" is often one-liner
JSON_LINE_RE = re.compile(r"^\{\"error\":\{.*\}\}$")

@dataclass
class Hit:
    file: str
    timestamp: str | None
    url: str | None
    status: int | None
    message: str | None


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    os.replace(tmp, STATE_PATH)


def parse_log(path: Path) -> Hit:
    timestamp = None
    url = None
    status = None
    message = None

    # Read only first ~500 lines + last ~200 lines to avoid huge bodies
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return Hit(file=path.name, timestamp=None, url=None, status=None, message=None)

    head = lines[:500]
    tail = lines[-200:] if len(lines) > 200 else []

    for line in head:
        if timestamp is None:
            m = TS_RE.match(line)
            if m:
                timestamp = m.group(1).strip()
                continue
        if url is None:
            m = URL_RE.match(line)
            if m:
                url = m.group(1).strip()
                continue

    for line in tail:
        if status is None:
            m = STATUS_RE.match(line)
            if m:
                try:
                    status = int(m.group(1))
                except Exception:
                    status = None
                continue
        if message is None and JSON_LINE_RE.match(line.strip()):
            try:
                obj = json.loads(line.strip())
                message = obj.get("error", {}).get("message")
            except Exception:
                pass

    return Hit(file=path.name, timestamp=timestamp, url=url, status=status, message=message)


def main() -> int:
    state = load_state()
    last_mtime = float(state.get("last_mtime", 0))

    if not LOG_DIR.exists():
        # Still update state to avoid spam
        save_state({"last_mtime": last_mtime, "last_run": datetime.now(timezone.utc).isoformat().replace('+00:00','Z')})
        return 0

    candidates = []
    for p in LOG_DIR.glob(GLOB):
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        if st.st_mtime > last_mtime:
            candidates.append((st.st_mtime, p))

    if not candidates:
        save_state({"last_mtime": last_mtime, "last_run": datetime.now(timezone.utc).isoformat().replace('+00:00','Z')})
        return 0

    candidates.sort(key=lambda x: x[0])

    hits: list[Hit] = []
    max_mtime = last_mtime

    for mtime, p in candidates:
        max_mtime = max(max_mtime, mtime)
        h = parse_log(p)
        if h.status == 401:
            hits.append(h)

    save_state({
        "last_mtime": max_mtime,
        "last_run": datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
        "scanned": len(candidates),
    })

    if not hits:
        return 0

    # Build a short alert message
    lines = []
    lines.append(f"CPA-plus 失败请求告警：发现 {len(hits)} 条 401（最近 5 分钟新增日志）")
    for i, h in enumerate(hits[:5], 1):
        ts = h.timestamp or "(no timestamp)"
        url = h.url or "(no url)"
        msg = (h.message or "(no message)").strip()
        # keep message short
        if len(msg) > 200:
            msg = msg[:200] + "…"
        lines.append(f"{i}. {ts} {url} :: {msg}")
    if len(hits) > 5:
        lines.append(f"… 还有 {len(hits)-5} 条未展开")

    sys.stdout.write("\n".join(lines) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
