#!/usr/bin/env bash
set -euo pipefail

# Nightly: scan RSS + build scored shortlist (AI/IT)
# Outputs:
#   workspace/rss/all-new.json
#   workspace/rss/brief.json
#   workspace/rss/github-ai.json

cd "$HOME/.openclaw/workspace"

# load env (no secrets printed)
set -a
source "$HOME/.openclaw/.env" 2>/dev/null || true
set +a

mkdir -p rss

# Ensure at least one known RSSHub feed is present (36kr-tech)
# blogwatcher output formatting may vary; match optional whitespace.
if ! blogwatcher blogs | grep -Eq "^[[:space:]]*36kr-tech[[:space:]]*$"; then
  blogwatcher add "36kr-tech" "https://www.36kr.com/information/technology" --feed-url "https://rss.lambda.xin/36kr/information/technology"
fi

# Scan all tracked sources
blogwatcher scan >/dev/null

# Collect NEW items from selected feeds (keep this list small & high-signal)
BLOGS=(
  "36kr-tech"
  "infoq"
  "openai-news"
  "google-research"
  "cloudflare"
  "kubernetes"
  "aws-news"
  "microsoft-research"
  "github-blog"
  "github-changelog"
  "hackernews"
  "v2ex-latest"
)

TMP_DIR="rss/_tmp"
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

for b in "${BLOGS[@]}"; do
  python3 scripts/rss_radar_fetch.py --blog "$b" --out "$TMP_DIR/${b}.json" --only-new --limit 50 || true
  # annotate blog name
  python3 - <<PY
import json
p="$TMP_DIR/${b}.json"
d=json.load(open(p,'r',encoding='utf-8'))
for it in d.get('items',[]):
    it['kind']='rss'
    it['sourceBlog']=d.get('blog')
open(p,'w',encoding='utf-8').write(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
PY
  
  

  
  
  
  
  
  

done

# Merge into all-new.json
python3 - <<'PY'
import json, glob
from datetime import datetime, timezone
items=[]
for fp in glob.glob('rss/_tmp/*.json'):
    d=json.load(open(fp,'r',encoding='utf-8'))
    items.extend(d.get('items') or [])
out={'generatedAt': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'), 'items': items}
open('rss/all-new.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('merged', len(items), 'items')
PY

# GitHub AI/LLM trending approximation (via gh search)
python3 scripts/github_ai_trending.py --days 7 --min-stars 200 --limit 20 --out rss/github-ai.json || true

# Score + select top
python3 scripts/rss_radar_select_and_brief.py --in rss/all-new.json --extra rss/github-ai.json --out rss/brief.json

# Mark all as read so next run focuses on new items only
blogwatcher read-all >/dev/null || true

python3 - <<'PY'
import json
p='rss/brief.json'
d=json.load(open(p,'r',encoding='utf-8'))
print('RSS nightly OK')
print('Top:', d['top']['title'])
print('URL:', d['top']['url'])
print('Top3:')
for i,it in enumerate(d['top10'][:3],1):
    print(f"{i}. {it['score']} {it['title']}")
PY
