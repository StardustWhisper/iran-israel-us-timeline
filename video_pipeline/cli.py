from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from .config import PipelineConfig
from .grok_client import create_video, download, map_internal_url_to_external
from .utils import read_json, sanitize_filename, sh, write_json


def cmd_plan(args: argparse.Namespace) -> None:
    cfg = PipelineConfig()
    total = args.seconds

    # 60s baseline: 10 shots x 6s
    per = args.shot_seconds
    n = max(1, total // per)
    # distribute remainder by adding +1s to first few shots
    remainder = total - n * per

    style = "真实摄影、电影感、稳重科技、冷色调、自然光、浅景深、镜头运动克制、无文字无水印"
    base_prompt = args.prompt.strip()

    shots = []
    for i in range(1, n + 1):
        sec = per + (1 if i <= remainder else 0)
        shot_prompt = (
            f"{base_prompt}. {style}. "
            f"Camera: slow dolly/steadycam, cinematic, realistic. No subtitles, no logos."
        )
        shots.append({
            "idx": i,
            "seconds": sec,
            "size": cfg.size,
            "quality": cfg.quality,
            "prompt": shot_prompt,
        })

    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + sanitize_filename(args.title)[:30]
    job = {
        "job_id": job_id,
        "title": args.title,
        "platform": "bilibili",
        "style": "realistic_tech",
        "total_seconds": total,
        "shots": shots,
        "created_at": int(time.time()),
    }

    job_dir = (cfg.jobs_dir() / job_id)
    write_json(job_dir / "job.json", job)
    print(str(job_dir / "job.json"))


def cmd_render(args: argparse.Namespace) -> None:
    cfg = PipelineConfig()
    job_path = Path(args.job)
    job = read_json(job_path)
    job_dir = job_path.parent

    clips_dir = job_dir / "clips"
    meta_dir = job_dir / "meta"
    out_dir = job_dir / "out"
    clips_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for shot in job["shots"]:
        idx = int(shot["idx"])
        print(f"[shot {idx}] generating...")
        res = create_video(
            prompt=shot["prompt"],
            seconds=int(shot["seconds"]),
            size=shot["size"],
            quality=shot["quality"],
            cfg=cfg,
        )
        write_json(meta_dir / f"shot-{idx:03d}-response.json", res.raw)

        if res.status != "completed" or not res.url:
            raise SystemExit(f"shot {idx} not completed: status={res.status}")

        url = map_internal_url_to_external(res.url, cfg)
        mp4_path = clips_dir / f"shot-{idx:03d}.mp4"
        download(url, mp4_path, cfg)

        # quick probe
        probe = sh([
            "ffprobe", "-hide_banner", "-v", "error",
            "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
            str(mp4_path)
        ], capture=True).strip()

        results.append({"idx": idx, "url": url, "path": str(mp4_path), "duration": probe})

    write_json(out_dir / "render_results.json", results)
    print(str(out_dir / "render_results.json"))


def cmd_assemble(args: argparse.Namespace) -> None:
    cfg = PipelineConfig()
    job_path = Path(args.job)
    job = read_json(job_path)
    job_dir = job_path.parent

    clips_dir = job_dir / "clips"
    out_dir = job_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Create concat list
    concat_list = out_dir / "concat.txt"
    lines = []
    for shot in job["shots"]:
        idx = int(shot["idx"])
        p = clips_dir / f"shot-{idx:03d}.mp4"
        if not p.exists():
            raise SystemExit(f"missing clip: {p}")
        lines.append(f"file '{p.as_posix()}'")
    concat_list.write_text("\n".join(lines) + "\n")

    final_mp4 = out_dir / "final.mp4"

    # Normalize to target size/fps, yuv420p
    w, h = cfg.size.split("x", 1)
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={cfg.fps}"
    )
    sh([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(final_mp4)
    ])

    print(str(final_mp4))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="video_pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Create a job.json plan")
    p_plan.add_argument("--title", required=True)
    p_plan.add_argument("--prompt", required=True, help="Base prompt for all shots")
    p_plan.add_argument("--seconds", type=int, default=60)
    p_plan.add_argument("--shot-seconds", type=int, default=6)
    p_plan.set_defaults(func=cmd_plan)

    p_render = sub.add_parser("render", help="Render clips from a job.json")
    p_render.add_argument("job")
    p_render.set_defaults(func=cmd_render)

    p_asm = sub.add_parser("assemble", help="Assemble final.mp4 from clips")
    p_asm.add_argument("job")
    p_asm.set_defaults(func=cmd_assemble)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
