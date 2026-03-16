from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"Missing env: {name}")
    return v


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path):
    return json.loads(path.read_text())


def sh(cmd: list[str], *, capture: bool = False) -> str:
    if capture:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return p.stdout
    subprocess.run(cmd, check=True)
    return ""


def sanitize_filename(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "job"
