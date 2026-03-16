from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Shot:
    idx: int
    prompt: str
    seconds: int
    size: str
    quality: str


@dataclass
class Job:
    job_id: str
    title: str
    style: str
    platform: str
    total_seconds: int
    shots: list[Shot]
