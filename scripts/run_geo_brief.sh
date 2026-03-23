#!/usr/bin/env bash
set -euo pipefail

# MVP geo/econ brief pipeline
# Outputs:
#   reports/geo/YYYY-MM-DD.md
#   reports/geo/YYYY-MM-DD.json

cd "$HOME/.openclaw/workspace"

set -a
source "$HOME/.openclaw/.env" 2>/dev/null || true
set +a

DATE=${DATE:-$(date +%Y-%m-%d)}
STATE_DIR="state/geo"
RSS_DIR="rss/geo"
TMP_DIR="$RSS_DIR/_tmp"
REPORT_DIR="reports/geo"
mkdir -p "$STATE_DIR" "$RSS_DIR" "$TMP_DIR" "$REPORT_DIR"

# Define feeds (simple high-signal geo/econ/energy/defense)
# You can add more by editing the list below.
FEEDS=(
  "reuters-world|https://www.reuters.com/world/|https://feeds.reuters.com/Reuters/worldNews"
  "reuters-business|https://www.reuters.com/business/|https://feeds.reuters.com/reuters/businessNews"
  "reuters-legal|https://www.reuters.com/legal/|https://feeds.reuters.com/reuters/legalNews"
  "reuters-commodities|https://www.reuters.com/markets/commodities/|https://feeds.reuters.com/reuters/commoditiesNews"
  "reuters-energy|https://www.reuters.com/business/energy/|https://feeds.reuters.com/reuters/energyNews"
  "reuters-aerospace|https://www.reuters.com/business/aerospace-defense/|https://feeds.reuters.com/reuters/aerospaceDefenseNews"
  "imf-news|https://www.imf.org/en/News|https://www.imf.org/en/News/rss"
  "worldbank-press|https://www.worldbank.org/en/news|https://www.worldbank.org/en/news/all?format=rss"
  "bloomberg-economics|https://www.bloomberg.com/economics|https://www.bloomberg.com/feeds/podcasts/economics.xml"
)

# Ensure feeds are registered in blogwatcher
BW_LIST=$(blogwatcher blogs | sed -E 's/\x1b\[[0-9;]*m//g')
for entry in "${FEEDS[@]}"; do
  name=$(printf '%s' "$entry" | cut -d'|' -f1)
  url=$(printf '%s' "$entry" | cut -d'|' -f2)
  feed=$(printf '%s' "$entry" | cut -d'|' -f3)
  if ! printf '%s\n' "$BW_LIST" | grep -Eq "^[[:space:]]*${name}[[:space:]]*$"; then
    blogwatcher add "$name" "$url" --feed-url "$feed" || true
  fi
  # scan each blog to minimize full scan time
  blogwatcher scan "$name" >/dev/null || true

  # fetch new items
  python3 scripts/geo_rss_fetch.py --blog "$name" --out "$TMP_DIR/${name}.json" --only-new --limit 80 || true
  # annotate source
  python3 - <<PY
import json
p="$TMP_DIR/${name}.json"
try:
    d=json.load(open(p,'r',encoding='utf-8'))
except Exception:
    d={"items":[]}
for it in d.get('items',[]):
    it['kind']='rss'
    it['sourceBlog']=d.get('blog') or "$name"
open(p,'w',encoding='utf-8').write(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
PY

done

# Merge all items
python3 - <<'PY'
import json, glob
from datetime import datetime, timezone
items=[]
for fp in glob.glob('rss/geo/_tmp/*.json'):
    try:
        d=json.load(open(fp,'r',encoding='utf-8'))
        items.extend(d.get('items') or [])
    except Exception:
        pass
out={'generatedAt': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'), 'items': items}
open('rss/geo/all-new.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('merged', len(items), 'items')
PY

# Rank and brief
python3 scripts/geo_rank.py --in rss/geo/all-new.json --out "rss/geo/brief.json" --top 12

# Output report
python3 scripts/geo_report.py --in rss/geo/brief.json --out "$REPORT_DIR/${DATE}.md" --date "$DATE"
cp "rss/geo/brief.json" "$REPORT_DIR/${DATE}.json"

# state files
cp "rss/geo/all-new.json" "$STATE_DIR/last_all.json"
cp "rss/geo/brief.json" "$STATE_DIR/last_brief.json"

# mark read
blogwatcher read-all >/dev/null || true

echo "GEO_BRIEF_OK date=$DATE out=$REPORT_DIR/${DATE}.md"
