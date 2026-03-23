#!/usr/bin/env python3
"""Geo/Econ emergency checker (MVP).

Goal:
- Run frequently (e.g., every 5 minutes).
- Detect potential high-impact geopolitical/economic headlines.
- If triggered, print ONE LINE starting with ALERT: ... so the cron wrapper can announce.

Notes:
- Uses blogwatcher feeds already registered by run_geo_brief.sh.
- Keeps a small local state file to avoid repeat alerts.
- Conservative defaults to avoid spam.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

STATE_PATH = Path("state/geo/emergency_state.json")
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Very conservative keyword triggers. Tune later.
TRIGGERS = [
    (re.compile(r"(direct\s+military\s+intervention|missile\s+strike|air\s+strike|invasion|mobilization)", re.I), "军事升级"),
    (re.compile(r"(oil\s+price\s+surge|brent\s+surges|wti\s+surges|output\s+cut|opec\+\s+emergency)", re.I), "能源冲击"),
    (re.compile(r"(sanction|export\s+control|tariff\s+hike|trade\s+ban|asset\s+freeze)", re.I), "制裁/贸易升级"),
    (re.compile(r"(shipping\s+halt|red\s+sea|strait\s+of\s+hormuz|blockade)", re.I), "航运通道风险"),
    (re.compile(r"(emergency\s+meeting|unscheduled\s+meeting|rate\s+decision\s+emergency)", re.I), "政策突发"),
]

COOLDOWN_SECONDS = int(os.environ.get("GEO_EMERGENCY_COOLDOWN_SECONDS", "3600"))  # 1h
MAX_CANDIDATES = int(os.environ.get("GEO_EMERGENCY_MAX_CANDIDATES", "40"))


def run(*cmd: str) -> str:
    return subprocess.check_output(list(cmd), text=True, stderr=subprocess.STDOUT)


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    st = load_state()
    last_alert_at = float(st.get("last_alert_at", 0))
    last_fp = str(st.get("last_fingerprint", ""))

    now = time.time()
    if now - last_alert_at < COOLDOWN_SECONDS:
        return 0

    # Get unread articles across all tracked feeds.
    # blogwatcher output is plain text; we match titles and ids.
    try:
        txt = run("blogwatcher", "articles", "--all")
    except Exception:
        return 0

    # Parse minimal: lines like: [123] [new] Title
    items = []
    for line in txt.splitlines():
        m = re.match(r"^\s*\[(\d+)\]\s*\[(\w+)\]\s*(.+?)\s*$", line)
        if not m:
            continue
        _id, status, title = m.group(1), m.group(2), m.group(3)
        if status != "new":
            continue
        items.append((int(_id), title.strip()))
        if len(items) >= MAX_CANDIDATES:
            break

    if not items:
        return 0

    # Find first trigger match.
    for _id, title in items:
        for rgx, label in TRIGGERS:
            if rgx.search(title):
                fp = f"{label}:{_id}:{title.lower()}"
                if fp == last_fp:
                    return 0
                st["last_alert_at"] = now
                st["last_fingerprint"] = fp
                st["last_title"] = title
                st["last_label"] = label
                save_state(st)
                print(f"ALERT: {label} — {title}")
                return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
