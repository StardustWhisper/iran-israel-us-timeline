from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelineConfig:
    # Grok2API
    base_url: str = "https://xai.lambda.xin/v1"
    api_key_env: str = "GROK2API_API_KEY"

    # Defaults (Bilibili)
    fps: int = 24
    size: str = "1280x720"  # 16:9
    quality: str = "high"   # ask for 720p

    workspace: Path = Path("/home/ubuntu/.openclaw/workspace")

    def jobs_dir(self) -> Path:
        return self.workspace / "video_pipeline" / "jobs"
