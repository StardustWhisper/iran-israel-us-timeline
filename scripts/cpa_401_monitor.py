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

STATUS_RE = re.compile(r"^\s*Status:\s*(\d+)")
URL_RE = re.compile(r"^\s*URL:\s*(\S+)")
TS_RE = re.compile(r"^\s*Timestamp:\s*(.+)")
# JSON error line in section "=== API RESPONSE ===" is often one-liner
JSON_LINE_RE = re.compile(r"^\{\"error\":\{.*\}\}$")

# Extra patterns for variant log formats
STATUS_ANY_RE = re.compile(r"\b(status|status_code|http_status)\b\s*[:=]\s*(\d{3})\b", re.I)
HTTP_LINE_RE = re.compile(r"\bHTTP/\d(?:\.\d)?\b\s+(\d{3})\b")

# Default behavior: if a 401 log may contain leaked tokens, delete the log file.
CPA_401_AUTO_DELETE = os.getenv("CPA_401_AUTO_DELETE", "1") == "1"

# Default: keep usage-limit accumulation silent unless explicitly enabled.
USAGE_LIMIT_ALERT_THRESHOLD = int(os.getenv("CPA_USAGE_LIMIT_ALERT_THRESHOLD", "10"))
USAGE_LIMIT_ALERT_ENABLED = os.getenv("CPA_USAGE_LIMIT_ALERT_ENABLED", "0") == "1"
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

    # Read only first ~500 lines + last ~400 lines to avoid huge bodies
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return Hit(file=path.name, timestamp=None, url=None, status=None, error_type=None, message=None)

    head = lines[:500]
    tail = lines[-400:] if len(lines) > 400 else lines

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

    # Try to detect status from multiple formats (tail is most likely to contain response)
    for line in tail:
        if status is None:
            m = STATUS_RE.match(line)
            if m:
                try:
                    status = int(m.group(1))
                except Exception:
                    status = None
                continue
            m2 = STATUS_ANY_RE.search(line)
            if m2:
                try:
                    status = int(m2.group(2))
                except Exception:
                    status = None
                continue
            m3 = HTTP_LINE_RE.search(line)
            if m3:
                try:
                    status = int(m3.group(1))
                except Exception:
                    status = None
                continue

        # Extract error json if present
        if JSON_LINE_RE.match(line.strip()):
            try:
                obj = json.loads(line.strip())
                if error_type is None:
                    error_type = obj.get("error", {}).get("type")
                if message is None:
                    message = obj.get("error", {}).get("message")
            except Exception:
                pass

        # Fallback: sometimes the file contains an inline "401" mention rather than Status:
        if status is None and "401" in line:
            m4 = re.search(r"\b401\b", line)
            if m4:
                status = 401

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
        # Use >= to avoid missing events when mtimes are equal (coarse FS timestamp)
        if st.st_mtime >= last_mtime:
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

    to_delete: list[Path] = []

    for mtime, p in candidates:
        max_mtime = max(max_mtime, mtime)
        h = parse_log(p)

        # Track usage limit errors (even if status is not 401)
        if h.error_type == "usage_limit_reached":
            usage_limit_hits += 1

        if h.status == 401:
            hits.append(h)
            if CPA_401_AUTO_DELETE:
                to_delete.append(p)

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

    # Priority 1: 401 immediate alert (+ auto delete to reduce token leakage risk)
    if hits:
        deleted = 0
        delete_errors: list[str] = []
        if CPA_401_AUTO_DELETE and to_delete:
            for p in to_delete:
                try:
                    p.unlink(missing_ok=True)
                    deleted += 1
                except Exception as e:
                    delete_errors.append(f"{p.name}: {type(e).__name__}")

        lines = []
        lines.append(f"CPA-plus 失败请求告警：发现 {len(hits)} 条 401（新增日志）")
        if CPA_401_AUTO_DELETE:
            lines.append(f"处理：已自动删除 {deleted}/{len(to_delete)} 个 401 日志文件（防止 token 泄漏）")
            if delete_errors:
                lines.append("删除失败：" + "; ".join(delete_errors[:3]) + ("…" if len(delete_errors) > 3 else ""))

        for i, h in enumerate(hits[:5], 1):
            ts = h.timestamp or "(no timestamp)"
            et = h.error_type or "unknown_error"
            # Do not echo full message to avoid leaking credentials; keep it very short.
            msg = (h.message or "").strip()
            if msg:
                msg = msg[:80] + ("…" if len(msg) > 80 else "")
            else:
                msg = "(no message)"
            u = (h.url or "").strip()
            if u:
                lines.append(f"{i}. {ts} status=401 type={et} url={u}")
            else:
                lines.append(f"{i}. {ts} status=401 type={et}")
        if len(hits) > 5:
            lines.append(f"… 还有 {len(hits)-5} 条未展开")
        sys.stdout.write("\n".join(lines) + "\n")
        return 2

    # Priority 2: usage_limit_reached accumulation alert (disabled by default; enable explicitly when needed)
    today_total = int(usage_limit_counts.get(usage_limit_date, 0))
    if USAGE_LIMIT_ALERT_ENABLED and today_total >= USAGE_LIMIT_ALERT_THRESHOLD and usage_limit_hits:
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
