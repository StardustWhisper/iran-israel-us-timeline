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
  # Reuters feeds currently NXDOMAIN in this environment; keep disabled for now.
  # "reuters-world|https://www.reuters.com/world/|https://feeds.reuters.com/reuters/worldNews"
  # "reuters-business|https://www.reuters.com/business/|https://feeds.reuters.com/reuters/businessNews"

  # RSSHub is protected by CF challenge (403) from this host at the moment; disable until we host our own RSSHub.
  # "rsshub-reuters-world|https://rsshub.app/reuters/world|https://rsshub.app/reuters/world"

  # Bloomberg often blocks/500s; disable.
  # "bloomberg-economics|https://www.bloomberg.com/economics|https://www.bloomberg.com/feeds/podcasts/economics.xml"

  # Stable, free, high-signal sources (validated with curl):
  "bbc-world|https://www.bbc.co.uk/news/world|https://feeds.bbci.co.uk/news/world/rss.xml"
  # AP RSS endpoints appear blocked/changed (returns HTML/404); keep disabled for now.
  # "ap-top|https://apnews.com/|https://apnews.com/apf-topnews?output=rss"
  "aljazeera-all|https://www.aljazeera.com/|https://www.aljazeera.com/xml/rss/all.xml"
  "dw-world|https://www.dw.com/en/top-stories/s-9097|https://rss.dw.com/rdf/rss-en-world"
  "un-news|https://news.un.org/|https://news.un.org/feed/subscribe/en/news/all/rss.xml"

  # Economics & markets (usually accessible):
  "ft-world|https://www.ft.com/world|https://www.ft.com/world?format=rss"
  "cnbc-world|https://www.cnbc.com/world/|https://www.cnbc.com/id/100727362/device/rss/rss.html"

  # Multi-language additions (validated with curl):
  # French:
  "lemonde-international|https://www.lemonde.fr/international/|https://www.lemonde.fr/international/rss_full.xml"
  "france24-fr|https://www.france24.com/fr/|https://www.france24.com/fr/rss"
  # German:
  "tagesschau|https://www.tagesschau.de/|https://www.tagesschau.de/xml/rss2"
  "zdf-nachrichten|https://www.zdf.de/nachrichten|https://www.zdf.de/rss/zdf/nachrichten"
  "spiegel-intl|https://www.spiegel.de/international/|https://www.spiegel.de/international/index.rss"
  # Japanese:
  "nhk-top|https://www3.nhk.or.jp/news/|https://www.nhk.or.jp/rss/news/cat0.xml"
  "nhk-world|https://www3.nhk.or.jp/news/|https://www3.nhk.or.jp/rss/news/cat3.xml"
  "asahi-headlines|https://www.asahi.com/|https://www.asahi.com/rss/asahi/newsheadlines.rdf"

  # Official/IO sources may block by region (IMF returned 403 here); keep disabled until reachable.
  # "imf-news|https://www.imf.org/|https://www.imf.org/external/rss/IMFNews.rss"
  # WorldBank RSS URL above returned 404 from this host; keep disabled until we find a reachable endpoint.
  # "worldbank-news|https://www.worldbank.org/en/news|https://www.worldbank.org/en/news/rss"
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

  # fetch NEW items first
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
    it['fresh']=True
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

# If no NEW items, fallback to pulling latest items (including already-read)
MERGED_COUNT=$(python3 - <<'PY'
import json
p='rss/geo/all-new.json'
d=json.load(open(p,'r',encoding='utf-8'))
print(len(d.get('items') or []))
PY
)

if [[ "$MERGED_COUNT" == "0" ]]; then
  echo "WARN: no NEW items; fallback to latest items from each feed" >&2
  for entry in "${FEEDS[@]}"; do
    name=$(printf '%s' "$entry" | cut -d'|' -f1)
    # overwrite per-feed json with latest items (may include read)
    python3 scripts/geo_rss_fetch.py --blog "$name" --out "$TMP_DIR/${name}.json" --limit 30 || true
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
    it['fresh']=(it.get('status')=='new')
    it['fallbackMode']='latest'
open(p,'w',encoding='utf-8').write(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
PY
  done

  # re-merge
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
out={'generatedAt': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'), 'items': items, 'fallbackUsed': True}
open('rss/geo/all-new.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('merged', len(items), 'items (fallback)')
PY
fi

# Rank and brief
python3 scripts/geo_rank.py --in rss/geo/all-new.json --out "rss/geo/brief.json" --top 12

# Output report (prefer HUGO fast brief; fallback to legacy report)
REPORT_JSON="$REPORT_DIR/${DATE}.json"
REPORT_MD="$REPORT_DIR/${DATE}.md"
cp "rss/geo/brief.json" "$REPORT_JSON"

HUGO_RAW="$TMP_DIR/hugo_geo_brief.json"
HUGO_STATUS="generated"
HUGO_PROMPT=$(python3 - <<'PY'
import json
from pathlib import Path
p = Path('rss/geo/brief.json')
try:
    data = json.loads(p.read_text(encoding='utf-8'))
except Exception:
    data = {}

items = data.get('topN') or []
# Keep a compact payload to avoid token bloat
payload = {
    'generatedAt': data.get('generatedAt'),
    'top': data.get('top') or {},
    'items': items,
}

print('你是 HUGO。禁止联网搜索。请基于【给定 JSON 数据】生成“地缘快报版”Markdown。')
print('硬性结构：')
print('1) 今日一句话')
print('2) 今日要点（<=5 条）')
print('3) 地缘事件清单（按主题分组）')
print('4) 传导链路（事件→渠道→变量）')
print('5) 风险雷达（未来24-72h可能触发条件，不预测）')
print('6) 日历（仅确定事项，可空）')
print('7) Sources')
print('硬性要求：')
print('- 每条要点/事件/链路/风险均需引用来源 URL（用括号或脚注形式，必须是原文链接）')
print('- Sources 列表需包含所有引用过的来源（标题 + URL）')
print('- 不要写概率，不给交易建议，不编造具体数字')
print('- 不确定的信息标注“待核实”')
print('- 只使用提供的来源，不要扩展或想象')
print('')
print('【数据 JSON】')
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
)

if ! bash scripts/openclaw_cli.sh agent --agent hugo --timeout 600 --json --message "$HUGO_PROMPT" > "$HUGO_RAW" 2>/dev/null; then
  HUGO_STATUS="failed"
else
  export HUGO_RAW REPORT_MD
  if ! python3 - <<'PY'
import json, pathlib, os, re
raw_path = pathlib.Path(os.environ['HUGO_RAW'])
report_md = pathlib.Path(os.environ['REPORT_MD'])
content = raw_path.read_text(encoding='utf-8')
start = content.find('{')
if start == -1:
    raise SystemExit('No JSON object found in ' + str(raw_path))
obj = json.loads(content[start:])

text = ''
if isinstance(obj, dict) and 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
    if payloads and isinstance(payloads, list):
        text = (payloads[0].get('text') or '').strip()
elif isinstance(obj, dict) and 'payloads' in obj:
    payloads = obj.get('payloads') or []
    if payloads and isinstance(payloads, list):
        text = (payloads[0].get('text') or '').strip()

if not text:
    raise KeyError(f"No text payload found. top_keys={list(obj.keys())}")

# Strip common prefatory phrases if any
patterns = [
    r'^以下是.*?\n+',
    r'^下面是.*?\n+',
    r'^当然可以.*?\n+',
]
for pat in patterns:
    text = re.sub(pat, '', text, flags=re.S)

report_md.write_text(text.strip() + '\n', encoding='utf-8')
print('WROTE', str(report_md))
PY
  then
    HUGO_STATUS="generated"
  else
    HUGO_STATUS="failed"
  fi
fi

if [[ "$HUGO_STATUS" != "generated" ]]; then
  python3 scripts/geo_report.py --in rss/geo/brief.json --out "$REPORT_MD" --date "$DATE"
fi

# state files
cp "rss/geo/all-new.json" "$STATE_DIR/last_all.json"
cp "rss/geo/brief.json" "$STATE_DIR/last_brief.json"

# mark read (avoid interactive prompt)
blogwatcher read-all -y >/dev/null || true

echo "GEO_BRIEF_OK date=$DATE out=$REPORT_DIR/${DATE}.md"
