from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import urllib.request

from .config import PipelineConfig
from .utils import require_env


@dataclass
class VideoResult:
    status: str
    url: str | None
    raw: dict


def _http_json(url: str, api_key: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        b = resp.read()
    return json.loads(b.decode("utf-8", errors="replace"))


def create_video(*, prompt: str, seconds: int, size: str, quality: str, cfg: PipelineConfig) -> VideoResult:
    api_key = require_env(cfg.api_key_env)
    url = f"{cfg.base_url.rstrip('/')}/videos"
    payload = {
        "model": "grok-imagine-1.0-video",
        "prompt": prompt,
        "size": size,
        "seconds": seconds,
        "quality": quality,
    }
    raw = _http_json(url, api_key, payload)
    return VideoResult(status=raw.get("status", ""), url=raw.get("url"), raw=raw)


def map_internal_url_to_external(u: str, cfg: PipelineConfig) -> str:
    """Some deployments return http://127.0.0.1:PORT/... which is not reachable externally.

    We rewrite it to cfg.base_url host, preserving path.
    """
    parsed = urlparse(u)
    if parsed.hostname in ("127.0.0.1", "localhost"):
        # cfg.base_url includes /v1; keep the path after /v1
        base = cfg.base_url.rstrip("/")
        # If path already starts with /v1, just join host
        return base.rsplit("/v1", 1)[0] + parsed.path
    return u


def download(url: str, out_path: Path, cfg: PipelineConfig) -> None:
    api_key = require_env(cfg.api_key_env)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    out_path.write_bytes(data)
