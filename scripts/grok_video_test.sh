#!/usr/bin/env bash
set -euo pipefail

OUTDIR=/home/ubuntu/.openclaw/workspace/video-out
mkdir -p "$OUTDIR"

# Load env (best-effort)
if [ -f /home/ubuntu/.openclaw/.env ]; then
  set +u
  # shellcheck disable=SC1091
  source /home/ubuntu/.openclaw/.env
  set -u
fi

: "${GROK2API_API_KEY:?GROK2API_API_KEY not set (expected in /home/ubuntu/.openclaw/.env)}"

REQ_JSON="$OUTDIR/test-video-request.json"
RESP_JSON="$OUTDIR/test-video-response.json"
URLS_TXT="$OUTDIR/test-video-urls.txt"

cat >"$REQ_JSON" <<'JSON'
{
  "model": "grok-imagine-1.0-video",
  "prompt": "Cinematic neon rainy street at night, slow dolly forward, shallow depth of field, 24fps, realistic lighting",
  "size": "1280x720",
  "seconds": 6,
  "quality": "standard"
}
JSON

echo "[1/3] Request written: $REQ_JSON"

echo "[2/3] Calling Grok2API /v1/videos ..."
curl -fsS "https://xai.lambda.xin/v1/videos" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GROK2API_API_KEY" \
  -d @"$REQ_JSON" \
  -o "$RESP_JSON"

echo "Response saved: $RESP_JSON"

echo "[3/3] Extracting URLs (if any) ..."
python3 - "$RESP_JSON" "$URLS_TXT" <<'PY'
import json, pathlib, re, sys
resp_path = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2])
obj = json.loads(resp_path.read_text())

urls=[]

def walk(x):
    if isinstance(x, dict):
        for k,v in x.items():
            if k in ('url','video_url','download_url') and isinstance(v,str):
                urls.append(v)
            walk(v)
    elif isinstance(x, list):
        for v in x:
            walk(v)
walk(obj)

# If the server returns HTML snippets, try to pull links from them.
htmls=[]

def find_html(x):
    if isinstance(x,str) and '<' in x and 'http' in x:
        htmls.append(x)
    elif isinstance(x, dict):
        for v in x.values():
            find_html(v)
    elif isinstance(x, list):
        for v in x:
            find_html(v)
find_html(obj)

if not urls and htmls:
    for h in htmls:
        urls += re.findall(r"https?://[^\s'\"<>]+", h)

# de-dupe
seen=[]
for u in urls:
    if u not in seen:
        seen.append(u)

out_path.write_text("\n".join(seen) + ("\n" if seen else ""))
print(f"FOUND_URLS {len(seen)}")
for u in seen[:10]:
    print(u)
PY

if [ -s "$URLS_TXT" ]; then
  echo "URLs saved: $URLS_TXT"
else
  echo "No direct URLs found in response. You may need to poll a task/status endpoint depending on server config."
fi
