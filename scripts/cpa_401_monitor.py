#!/usr/bin/env python3
"""Monitor CLIProxyAPIPlus error logs.

- Scans deploy-cli-proxy/logs/error-*.log for new files since last run.
- Extracts a small, non-sensitive summary (timestamp/url/status/error.type/error.message).
- Tracks daily counts of error.type == "usage_limit_reached".
- Writes state to workspace/memory/cpa_401_monitor_state.json.

Exit codes:
  0: nothing to alert
  2: should alert (stdout contains alert text)
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

LOG_DIR = Path("/home/ubuntu/github/deploy-cli-proxy/logs")
STATE_PATH = Path("/home/ubuntu/.openclaw/workspace/memory/cpa_401_monitor_state.json")
GLOB = "error-*.log"

STATUS_RE = re.compile(r"^Status:\s*(\d+)")
URL_RE = re.compile(r"^URL:\s*(\S+)")
TS_RE = re.compile(r"^Timestamp:\s*(.+)")
# JSON error line in section "=== API RESPONSE ===" is often one-liner
JSON_LINE_RE = re.compile(r"^\{\"error\":\{.*\}\}$")

# Default: alert when usage_limit_reached accumulates to this count in a day
USAGE_LIMIT_ALERT_THRESHOLD = int(os.getenv("CPA_USAGE_LIMIT_ALERT_THRESHOLD", "10"))
LOCAL_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

@dataclass
class Hit:
    file: str
    timestamp: str | None
    url: str | None
    status: int | None
    error_type: str | None
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
    error_type = None
    message = None

    # Read only first ~500 lines + last ~200 lines to avoid huge bodies
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return Hit(file=path.name, timestamp=None, url=None, status=None, error_type=None, message=None)

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
        if JSON_LINE_RE.match(line.strip()):
            try:
                obj = json.loads(line.strip())
                if error_type is None:
                    error_type = obj.get("error", {}).get("type")
                if message is None:
                    message = obj.get("error", {}).get("message")
            except Exception:
                pass

    return Hit(file=path.name, timestamp=timestamp, url=url, status=status, error_type=error_type, message=message)


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

    # Per-day counter for usage_limit_reached
    usage_limit_hits = 0
    usage_limit_date = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    usage_limit_counts = dict(state.get("usage_limit_counts", {}))
    usage_limit_counts.setdefault(usage_limit_date, 0)

    for mtime, p in candidates:
        max_mtime = max(max_mtime, mtime)
        h = parse_log(p)

        # Track usage limit errors (even if status is not 401)
        if h.error_type == "usage_limit_reached":
            usage_limit_hits += 1

        if h.status == 401:
            hits.append(h)

    # Update rolling per-day counts
    if usage_limit_hits:
        usage_limit_counts[usage_limit_date] = int(usage_limit_counts.get(usage_limit_date, 0)) + usage_limit_hits

    # Keep only recent 14 days to avoid unbounded growth
    try:
        cutoff = datetime.now(LOCAL_TZ) - timedelta(days=14)
        usage_limit_counts = {
            k: v for k, v in usage_limit_counts.items()
            if datetime.strptime(k, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ) >= cutoff
        }
    except Exception:
        pass

    save_state({
        "last_mtime": max_mtime,
        "last_run": datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
        "scanned": len(candidates),
        "usage_limit_counts": usage_limit_counts,
    })

    # Priority 1: 401 immediate alert
    if hits:
        lines = []
        lines.append(f"CPA-plus 失败请求告警：发现 {len(hits)} 条 401（最近 5 分钟新增日志）")
        for i, h in enumerate(hits[:5], 1):
            ts = h.timestamp or "(no timestamp)"
            url = h.url or "(no url)"
            msg = (h.message or "(no message)").strip()
            if len(msg) > 200:
                msg = msg[:200] + "…"
            lines.append(f"{i}. {ts} {url} :: {msg}")
        if len(hits) > 5:
            lines.append(f"… 还有 {len(hits)-5} 条未展开")
        sys.stdout.write("\n".join(lines) + "\n")
        return 2

    # Priority 2: usage_limit_reached accumulation alert (threshold per day)
    today_total = int(usage_limit_counts.get(usage_limit_date, 0))
    if today_total >= USAGE_LIMIT_ALERT_THRESHOLD and usage_limit_hits:
        sys.stdout.write(
            "\n".join([
                f"CPA-plus 用量告警：检测到 usage_limit_reached（今日累计 {today_total} 次，阈值 {USAGE_LIMIT_ALERT_THRESHOLD}）",
                "建议：检查是否触发了上游配额/并发/速率限制，并考虑降级/重试退避。",
            ]) + "\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
