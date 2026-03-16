# video_pipeline

A small, reproducible video generation pipeline for Grok2API + ffmpeg.

Target preset (per Lambda):
- Platform: Bilibili (16:9)
- Duration: 60s
- Style: stable tech / realistic photography
- Voice: steady tech (TTS optional; not enabled by default)

## Concepts
- **Job**: a folder under `jobs/<job_id>/` with `job.json` (plan) and generated assets.
- **Shots**: each shot is generated via Grok2API `/v1/videos`, then downloaded.
- **Assemble**: concatenates clips, normalizes fps/size, optionally adds simple title card.

## Quickstart
1) Create a plan:

```bash
python3 -m video_pipeline plan \
  --title "Test" \
  --prompt "AI data center, cinematic" \
  --out jobs
```

2) Render the plan:

```bash
python3 -m video_pipeline render jobs/<job_id>/job.json
```

3) Assemble:

```bash
python3 -m video_pipeline assemble jobs/<job_id>/job.json
```

Outputs go to `jobs/<job_id>/out/`.
