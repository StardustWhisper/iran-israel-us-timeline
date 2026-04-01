#!/usr/bin/env bash
set -euo pipefail

# Nightly: scan RSS + build scored shortlist (AI/IT)
# Sources: 保留原有信息源，并新增日语/韩语/俄语极客向 RSS
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
# blogwatcher output may include ANSI colors; strip them before matching.
BW_LIST=$(blogwatcher blogs | sed -E 's/\x1b\[[0-9;]*m//g')
if ! printf '%s\n' "$BW_LIST" | grep -Eq "^[[:space:]]*36kr-tech[[:space:]]*$"; then
  blogwatcher add "36kr-tech" "https://www.36kr.com/information/technology" --feed-url "https://rss.lambda.xin/36kr/information/technology"
fi

# Scan all tracked sources
blogwatcher scan >/dev/null

# Collect NEW items from selected feeds (keep this list small & high-signal)
BLOGS=(
  # 原有信息源（保留）
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

  # 新增：日语极客/工程圈
  "zenn-ai"
  "zenn-sre"
  "qiita-sre"
  "qiita-kubernetes"
  "hatena-hot-it"

  # 新增：韩语极客/工程圈
  "kakao-tech"
  "line-tech-ko"
  "naver-d2"

  # 新增：俄语极客/工程圈
  "habr-devops"
  "habr-kubernetes"
  "habr-ai"
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

# (A2A) Ask HUGO to generate a lightweight "topic pack" for top candidates.
# - Purpose: help the morning pipeline draft faster with better angle/outline.
# - Constraint: do NOT browse the web here; do NOT invent specific numbers/facts.
HUGO_PACK_STATUS="skipped"
HUGO_PACK_RAW="rss/_tmp/nightly_hugo_pack_raw.json"
HUGO_PACK_OUT="rss/nightly_pack.json"
mkdir -p rss/_tmp

TOP3_LIST=$(python3 - <<'PY'
import json
p='rss/brief.json'
d=json.load(open(p,'r',encoding='utf-8'))
items=(d.get('top10') or [])[:3]
lines=[]
for i,it in enumerate(items,1):
    title=(it.get('title') or '').strip()
    url=(it.get('url') or '').strip()
    score=it.get('score')
    lines.append(f"{i}) {title}\n   - url: {url}\n   - score: {score}")
print("\n".join(lines))
PY
)

if bash scripts/openclaw_cli.sh agent --agent hugo --to +15555550123 --timeout 600 --json --message "你是 HUGO，现在只做‘选题包’整理，不写长文、不联网搜索。

我会给你 3 个候选选题（标题+链接）。请你输出一个【严格 JSON 对象】（不要 markdown，不要前后解释），用于给 morning 流水线直接消费。

候选选题：
${TOP3_LIST}

硬性要求：
- 只能基于标题与常识推理，不能声称你‘查到’了什么
- 不要编造具体数字/版本号/公司内部细节；不确定就写 null 或用保守措辞
- JSON 结构必须是：
{
  \"generatedAt\": \"ISO8601\",
  \"items\": [
    {
      \"rank\": 1,
      \"title\": \"...\",
      \"url\": \"...\",
      \"thesis\": \"一句话结论（可发布的观点，不含虚构事实）\",
      \"whyReadersCare\": [\"点1\",\"点2\"],
      \"whatHappened\": [\"点1\",\"点2\"],
      \"mechanism\": [\"机制点1\",\"机制点2\",\"机制点3\"],
      \"misconceptions\": [\"误区1\",\"误区2\"],
      \"outline\": [\"段落1\",\"段落2\",\"段落3\",\"段落4\"],
      \"keywords\": [\"关键词1\",\"关键词2\"],
      \"wechatAngle\": \"更偏科普/更偏产业/更偏安全/更偏工具链 等\",
      \"coverPrompt\": \"给 DALI 的封面提示词：必须无文字/无logo/干净留白\",
      \"figurePrompts\": [\"配图1提示词\",\"配图2提示词\"]
    }
  ]
}
" > "$HUGO_PACK_RAW"; then
  # Normalize: extract first JSON object from payload and write to rss/nightly_pack.json
  if python3 - <<'PY'
import json, pathlib, os, sys
# Ensure workspace/scripts is importable
sys.path.insert(0, os.path.join(os.path.expanduser('~/.openclaw/workspace'), 'scripts'))
from fix_json_quotes import parse_messy_json

raw_path = pathlib.Path('rss/_tmp/nightly_hugo_pack_raw.json')
out_path = pathlib.Path('rss/nightly_pack.json')
text = raw_path.read_text(encoding='utf-8')

obj = parse_messy_json(text)

# openclaw agent wrapper
payload_text = ''
if isinstance(obj, dict) and 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
    if payloads:
        payload_text = (max(payloads, key=lambda p: len((p.get('text') or '').strip())).get('text') or '').strip()
elif isinstance(obj, dict) and 'payloads' in obj:
    payloads = obj.get('payloads') or []
    if payloads:
        payload_text = (max(payloads, key=lambda p: len((p.get('text') or '').strip())).get('text') or '').strip()

if not payload_text:
    raise SystemExit('no payload text')

pack = parse_messy_json(payload_text)
out_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('WROTE', str(out_path))
PY
  then
    HUGO_PACK_STATUS="ok"
  else
    HUGO_PACK_STATUS="failed"
  fi
else
  HUGO_PACK_STATUS="failed"
fi

# Mark all as read so next run focuses on new items only
blogwatcher read-all >/dev/null || true

python3 - <<'PY'
import json
p='rss/brief.json'
d=json.load(open(p,'r',encoding='utf-8'))
print('RSS nightly OK')
print('Version: rss_nightly v2026-03-23-a2a-pack')
print('Top:', d['top']['title'])
print('URL:', d['top']['url'])
print('Top3:')
for i,it in enumerate(d['top10'][:3],1):
    print(f"{i}. {it['score']} {it['title']}")
PY

echo "HUGO pack: ${HUGO_PACK_STATUS}"
