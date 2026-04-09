#!/usr/bin/env bash
set -euo pipefail

# Morning: use last night's brief -> ask HUGO to draft -> generate cover -> publish to WeChat drafts
# This script is designed to be run under OpenClaw cron via exec.

cd "$HOME/.openclaw/workspace"

set -a
source "$HOME/.openclaw/.env" 2>/dev/null || true
set +a

STAGE="init"
WEB_RESEARCH_STATUS="pending"
ARTICLE_STATUS="pending"
COVER_STATUS="pending"
NOTION_SYNC_STATUS="pending"
WECHAT_MEDIA_ID=""

# cleanup helper must be defined BEFORE trap
cleanup_wechat_draft() {
  if [[ -n "${WECHAT_MEDIA_ID:-}" ]]; then
    echo "CLEANUP: deleting wechat draft media_id=${WECHAT_MEDIA_ID}" >&2
    python3 "$HOME/.openclaw/workspace/scripts/wechat_draft_delete.py" --media-id "$WECHAT_MEDIA_ID" >/dev/null 2>&1 || true
  fi
}

on_error() {
  local exit_code=$?
  # best-effort cleanup to avoid leaving broken drafts in WeChat
  cleanup_wechat_draft || true
  echo "MORNING_FAIL stage=$STAGE web_research_status=$WEB_RESEARCH_STATUS article_status=$ARTICLE_STATUS cover_status=$COVER_STATUS notion_status=$NOTION_SYNC_STATUS media_id=$WECHAT_MEDIA_ID" >&2
  exit "$exit_code"
}
trap on_error ERR

BRIEF="rss/brief.json"

# Allow picking rank N from last night's shortlist (top10)
# - Env override: MORNING_PICK_RANK=2
# - One-shot file override (preferred for ad-hoc runs): rss/morning_pick_rank_once.txt (will be deleted after read)
MORNING_PICK_RANK="${MORNING_PICK_RANK:-}"
if [[ -z "${MORNING_PICK_RANK}" ]] && [[ -f "rss/morning_pick_rank_once.txt" ]]; then
  MORNING_PICK_RANK="$(cat rss/morning_pick_rank_once.txt | head -n 1 | tr -cd '0-9' || true)"
  rm -f rss/morning_pick_rank_once.txt || true
fi
MORNING_PICK_RANK="${MORNING_PICK_RANK:-1}"
export MORNING_PICK_RANK

if [[ ! -f "$BRIEF" ]]; then
  # backward compat
  if [[ -f "rss/36kr-tech-brief.json" ]]; then
    BRIEF="rss/36kr-tech-brief.json"
  else
    echo "Missing rss/brief.json; run nightly first" >&2
    exit 2
  fi
fi

export BRIEF

SOURCE_TITLE=$(python3 - <<'PY'
import json, os
p=os.environ['BRIEF']
d=json.load(open(p,'r',encoding='utf-8'))
rank = int(os.environ.get('MORNING_PICK_RANK','1') or '1')
items = d.get('top10') or []
# rank is 1-based
idx = max(0, rank-1)
if items and idx < len(items):
    it = items[idx]
else:
    it = d.get('top') or {}
print(it.get('title') or '')
PY
)
URL=$(python3 - <<'PY'
import json, os
p=os.environ['BRIEF']
d=json.load(open(p,'r',encoding='utf-8'))
rank = int(os.environ.get('MORNING_PICK_RANK','1') or '1')
items = d.get('top10') or []
idx = max(0, rank-1)
if items and idx < len(items):
    it = items[idx]
else:
    it = d.get('top') or {}
print(it.get('url') or '')
PY
)

DATE_DIR=$(date +%Y%m%d)
RUN_SUFFIX="${RUN_SUFFIX:-}"
OUT_DIR="$HOME/.openclaw/workspace/wechat-publisher-out/auto/$DATE_DIR${RUN_SUFFIX}"
mkdir -p "$OUT_DIR"

# 0) Generate our OWN publishable title + viewpoint (must NOT equal source title)
# Requirements (per Lambda):
# - Title must differ from the source title
# - Do secondary topic selection: form a clear viewpoint based on the recommended topic
# Use a per-run session id to avoid Hugo session lock / cross-run contamination
HUGO_SESSION_ID="rss-morning:${DATE_DIR}${RUN_SUFFIX}"
export HUGO_SESSION_ID

STAGE="title"
TITLE_AGENT="${TITLE_AGENT:-linus}"
TITLE_SESSION_ID="${HUGO_SESSION_ID}:title"
TITLE_JSON="$OUT_DIR/title.json"
export SOURCE_TITLE URL TITLE_JSON TITLE_AGENT TITLE_SESSION_ID
TITLE=$(bash scripts/openclaw_cli.sh agent --agent "$TITLE_AGENT" --session-id "$TITLE_SESSION_ID" --to +15555550123 --timeout 300 --json --message "你现在做【二次选题】。我会给你：源标题 + 源链接 + 目标平台（公众号）。

请输出【严格 JSON 对象】（不要 markdown、不要前后解释）：
{
  \"title\": \"新的中文标题（≤28字，不要与源标题相同，也不要同义改写得太像；要有观点/结论倾向）\",
  \"thesis\": \"一句话观点（可写进文章开头的核心判断）\",
  \"angle\": \"文章角度（科普/工程实践/产品拆解/方法论 等）\",
  \"keywords\": [\"关键词1\",\"关键词2\"]
}

输入：
- 源标题：${SOURCE_TITLE}
- 源链接：${URL}

硬性规则：
- title 不能包含 URL
- title 不要出现‘深度解读/重磅/全网最全’这类营销词
- 如果你拿不准事实，就把观点写成‘趋势/机制/取舍’而不是具体数字
" > "$TITLE_JSON" && python3 - <<'PY'
import json, os, re
p=os.environ['TITLE_JSON']
text=open(p,'r',encoding='utf-8').read()
start=text.find('{')
obj=json.loads(text[start:])
new_title=(obj.get('title') or '').strip()
source=os.environ.get('SOURCE_TITLE','').strip()
# Fallbacks / guards
if not new_title:
    new_title = source
if new_title == source:
    new_title = new_title + '：我们真正该关注什么'
# overly similar (simple heuristic)
if len(new_title) >= 8 and len(source) >= 8:
    a=set(re.findall(r"[\u4e00-\u9fff]{1,}|[a-z0-9]{2,}", new_title.lower()))
    b=set(re.findall(r"[\u4e00-\u9fff]{1,}|[a-z0-9]{2,}", source.lower()))
    j=len(a&b)/max(1,len(a|b))
    if j>=0.75:
        new_title = new_title + '（换个角度看）'
print(new_title)
PY
) || TITLE="$SOURCE_TITLE"

# expose to later steps
export SOURCE_TITLE URL TITLE TITLE_JSON

# 1) Build research briefs so HUGO can synthesize, not merely rewrite the source link.
STAGE="research"
RESEARCH_JSON="$OUT_DIR/research.json"
export RESEARCH_JSON

python3 scripts/rss_topic_research.py \
  --title "$TITLE" \
  --source-url "$URL" \
  --corpus "rss/all-new.json" \
  --out "$RESEARCH_JSON"

TOPIC_TEMPLATE=$(python3 - <<'PY'
import json, os
p = os.path.expanduser(os.environ['RESEARCH_JSON'])
d = json.load(open(p, 'r', encoding='utf-8'))
print(d.get('template') or 'general-tech')
PY
)
export TOPIC_TEMPLATE

# 1a) Ask an agent to build "Claim Cards" (观点卡片) — best effort.
# Goal: make the final article structurally NOT a paraphrase of the source.
WEB_RESEARCH_STATUS="ok"
CLAIMS_RAW="$OUT_DIR/claims_raw.json"
CLAIMS_JSON="$OUT_DIR/claims.json"
export CLAIMS_RAW CLAIMS_JSON

normalize_claims() {
  python3 - <<'PY'
import json, os, pathlib, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.environ.get('SCRIPT_DIR','scripts')), 'scripts'))
from fix_json_quotes import fix_json_quotes
raw_path = pathlib.Path(os.environ['CLAIMS_RAW'])
out_path = pathlib.Path(os.environ['CLAIMS_JSON'])
text = raw_path.read_text(encoding='utf-8')
start = text.find('{')
if start == -1:
    raise SystemExit('no json')
obj = json.loads(text[start:])

payloads = []
if isinstance(obj, dict) and 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
elif isinstance(obj, dict) and 'payloads' in obj:
    payloads = obj.get('payloads') or []

if not payloads:
    raise SystemExit('no payloads')

inner = (max(payloads, key=lambda p: len((p.get('text') or '').strip())).get('text') or '').strip()
start2 = inner.find('{')
if start2 == -1:
    raise SystemExit('payload has no json')
raw_json = inner[start2:]
try:
    claims = json.loads(raw_json)
except json.JSONDecodeError:
    claims = json.loads(fix_json_quotes(raw_json))
claims['qualityOk'] = bool(claims.get('cards')) and bool(claims.get('originalComponents'))
out_path.write_text(json.dumps(claims, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('WROTE', str(out_path))
PY
}

# Try twice; sometimes the agent returns an empty payload list.
# Use a dedicated research agent so HUGO model changes don't break JSON-only research.
CLAIMS_AGENT="${CLAIMS_AGENT:-linus}"
CLAIMS_SESSION_ID="${HUGO_SESSION_ID}:claims"
export CLAIMS_AGENT CLAIMS_SESSION_ID

CLAIMS_OK=0
for attempt in 1 2; do
  if bash scripts/openclaw_cli.sh agent --agent "$CLAIMS_AGENT" --session-id "$CLAIMS_SESSION_ID" --to +15555550123 --timeout 900 --json --message "你现在不是写文章，而是在搭建【观点卡片（Claim Cards）】。

输入：
- 选题标题：${TITLE}
- 触发标题（仅供参考）：${SOURCE_TITLE}
- 背景阅读种子链接（来自 top10，可为空；不要复述其结构/句子）：
${SEED_URLS:-}

任务（必须以“原创专栏”为目标，不是改写新闻）：
1) 联网搜索并阅读多方资料（至少 3 个不同站点/来源，允许多语种），把你准备在文中主张的观点拆成 8-12 张卡片。
2) 每张卡片必须可写成一句“主张句”，并带 1-3 条证据来源（只做内部支撑；最终文章不要放链接）。
3) 给出 3 个“原创结构件”，用于让文章明显不像新闻复述（例如：验收门槛/检查表/分层模型/决策树/上线守则/回滚方案）。
4) 给出 4-8 条“反复述规则”，明确禁止沿用任何单篇文章的段落顺序/小标题/措辞。

只输出【严格 JSON】（不要 markdown，不要解释）：
{
  \"topic\": \"${TITLE}\",
  \"thesis\": \"一句话观点\",
  \"cards\": [
    {
      \"claim\": \"可直接写进正文的一句话主张\",
      \"confidence\": \"high|med|low\",
      \"evidence\": [
        {\"title\": \"来源标题\", \"url\": \"来源链接\", \"type\": \"official|media|research|analysis\", \"lang\": \"zh|en|ja|ko|ru|...\", \"note\": \"这条证据支持什么\"}
      ]
    }
  ],
  \"originalComponents\": [\"组件1\", \"组件2\", \"组件3\"],
  \"antiParaphraseRules\": [\"规则1\", \"规则2\"]
}

硬性要求：
- cards 里至少 2 张卡片必须来自非中文来源（ja/ko/ru/en 均可）
- 如果不确定就把 confidence 降到 low，low 的观点后续写作时不要当硬事实
" > "$CLAIMS_RAW"; then
    if normalize_claims; then
      CLAIMS_OK=1
      break
    fi
  fi
  sleep 1
done

if [[ "$CLAIMS_OK" != "1" ]]; then
  WEB_RESEARCH_STATUS="failed"
  python3 - <<'PY' > "$CLAIMS_JSON"
import json, os
print(json.dumps({
    'topic': os.environ.get('TITLE',''),
    'thesis': '',
    'cards': [],
    'originalComponents': [],
    'antiParaphraseRules': [],
    'qualityOk': False,
}, ensure_ascii=False, indent=2))
PY
fi

RESEARCH_BRIEF=$(python3 - <<'PY'
import json, os
rss_p = os.path.expanduser(os.environ['RESEARCH_JSON'])
claims_p = os.path.expanduser(os.environ.get('CLAIMS_JSON',''))
rss = json.load(open(rss_p, 'r', encoding='utf-8'))
claims = None
if claims_p and os.path.exists(claims_p):
    try:
        claims = json.load(open(claims_p, 'r', encoding='utf-8'))
    except Exception:
        claims = None

# Optional: nightly pack generated by HUGO at 23:00 (no web browsing).
pack_path = os.path.expanduser(os.environ.get('NIGHTLY_PACK_JSON', 'rss/nightly_pack.json'))
pack = None
if os.environ.get('USE_NIGHTLY_PACK', '1') == '1':
    try:
        pack = json.load(open(pack_path, 'r', encoding='utf-8'))
    except Exception:
        pack = None

# pick best matching pack item (url match first), fallback to rank=1
pack_item = None
if pack and isinstance(pack, dict):
    items = pack.get('items') or []
    src_url = (os.environ.get('URL') or '').strip()
    for it in items:
        if (it.get('url') or '').strip() and src_url and (it.get('url') or '').strip() == src_url:
            pack_item = it
            break
    if not pack_item and items:
        pack_item = items[0]

lines = []
lines.append(f"选题模板：{rss.get('template') or 'general-tech'}")
lines.append('补充资料（来自当前 RSS 候选池，可用于拓展背景，不要逐条照抄）：')
for i, it in enumerate(rss.get('related') or [], 1):
    lines.append(f"{i}. [{it.get('source')}] {it.get('title')} — {it.get('url')}")

if pack_item:
    lines.append('')
    lines.append('HUGO 选题包（由 nightly 生成，不联网；用于结构/角度/类比，不可当成事实来源）：')
    thesis = (pack_item.get('thesis') or '').strip()
    if thesis:
        lines.append(f"- 一句话主张：{thesis}")
    wa = (pack_item.get('wechatAngle') or '').strip()
    if wa:
        lines.append(f"- 公众号角度：{wa}")
    kw = pack_item.get('keywords') or []
    if kw:
        lines.append('- 关键词：' + '、'.join([str(k).strip() for k in kw if str(k).strip()]))
    outline = pack_item.get('outline') or []
    if outline:
        lines.append('- 建议结构：')
        for i, s in enumerate(outline, 1):
            s = str(s).strip()
            if s:
                lines.append(f"  {i}. {s}")
    mech = pack_item.get('mechanism') or []
    if mech:
        lines.append('- 可讲清的机制点：')
        for s in mech:
            s = str(s).strip()
            if s:
                lines.append(f"  - {s}")
    mis = pack_item.get('misconceptions') or []
    if mis:
        lines.append('- 容易误解的点：')
        for s in mis:
            s = str(s).strip()
            if s:
                lines.append(f"  - {s}")

if claims and (claims.get('cards') or claims.get('originalComponents') or claims.get('antiParaphraseRules')):
    lines.append('')
    lines.append('观点卡片（Claim Cards，来自联网搜索；写作时只用这些观点组织文章，避免复述源文）：')
    lines.append(f"- 质量检查：{'通过' if claims.get('qualityOk') else '偏弱，写作要更保守'}")
    if claims.get('thesis'):
        lines.append(f"- 核心观点：{claims.get('thesis')}")
    # show cards (without flooding)
    cards = claims.get('cards') or []
    for i, c in enumerate(cards[:10], 1):
        claim = (c.get('claim') or '').strip()
        conf = (c.get('confidence') or '').strip()
        if claim:
            lines.append(f"- 卡片{i}({conf}): {claim}")
    comps = claims.get('originalComponents') or []
    if comps:
        lines.append('- 原创结构件（必须落到正文）：')
        for s in comps[:6]:
            s = str(s).strip()
            if s:
                lines.append(f"  - {s}")
    rules = claims.get('antiParaphraseRules') or []
    if rules:
        lines.append('- 反复述规则：')
        for s in rules[:6]:
            s = str(s).strip()
            if s:
                lines.append(f"  - {s}")

print('\\n'.join(lines))
PY
)

ARTICLE_STRUCTURE=$(python3 - <<'PY'
import os, hashlib
m = os.environ.get('TOPIC_TEMPLATE', 'general-tech')
title = os.environ.get('TITLE','')
seed = int(hashlib.md5(title.encode('utf-8')).hexdigest()[:8], 16) if title else 0

# Rotate structure variants to avoid "模板感"
variants = {
  'general-tech': [
    '结构（观点先行）：开头直接给结论→用3个自拟小标题展开3张关键观点卡→给一张可执行清单→读者任务→收束（不要用固定“发生了什么/常见误区”标题）',
    '结构（反直觉）：先抛一个常见误解→给你的判断→分2-4段讲清机制→给“避坑清单/上线守则”→读者任务→结尾留3个观察信号',
    '结构（工具箱）：用一句话定义问题→给分层模型(3层)→每层给1个落地动作→给检查表→读者任务→总结',
  ],
  'security': [
    '结构（风险分级）：一句话风险结论→风险分级(低/中/高)→每级给1个工程对策→检查表→读者任务→结尾',
    '结构（攻防路径）：先讲“最常见的失败路径”→再讲正确做法→把防护写成上线守则→读者任务→结尾',
  ],
  'agent-industry': [
    '结构（产业机制）：一句话观点→“谁在为谁买单”机制拆解→3张观点卡分别展开→给落地路线图(3步)→读者任务→结尾',
    '结构（产品形态）：先定义“这类产品真正卖的是什么”→对比两种形态→给选择清单→读者任务→结尾',
  ],
  'compute-industry': [
    '结构（成本账本）：一句话观点→成本结构拆解(固定/可变/隐藏)→给3条降本杠杆→检查表→读者任务→结尾',
    '结构（瓶颈迁移）：一句话观点→瓶颈从A迁到B→用3个信号解释→给下一步关注清单→读者任务→结尾',
  ],
}

key = m if m in variants else 'general-tech'
arr = variants[key]
print(arr[seed % len(arr)])
PY
)

# 2) Let HUGO write article (markdown) based on secondary topic + web research — best effort.
STAGE="drafting"
ARTICLE_JSON="$OUT_DIR/hugo.json"
ARTICLE_MD_RAW="$OUT_DIR/article_raw.md"
ARTICLE_STATUS="generated"
export ARTICLE_JSON ARTICLE_MD_RAW RESEARCH_JSON CLAIMS_JSON

THESIS=$(python3 - <<'PY'
import json, os
p=os.environ.get('TITLE_JSON','')
if not p or not os.path.exists(p):
    print('')
    raise SystemExit(0)
text=open(p,'r',encoding='utf-8').read()
start=text.find('{')
obj=json.loads(text[start:])
# unwrap openclaw agent wrapper
if 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
    if payloads:
        t = (payloads[0].get('text') or '').strip()
        start2 = t.find('{')
        if start2 != -1:
            try:
                inner = json.loads(t[start2:])
                obj = inner
            except Exception:
                pass
print((obj.get('thesis') or '').strip())
PY
)

# Draft generation via direct Grok2API /chat/completions (stream=false) to avoid OpenClaw agent session bloat.
STAGE="drafting"
ARTICLE_JSON="$OUT_DIR/hugo.json"
ARTICLE_MD_RAW="$OUT_DIR/article_raw.md"
ARTICLE_STATUS="generated"
export ARTICLE_JSON ARTICLE_MD_RAW RESEARCH_JSON CLAIMS_JSON

COMPACT_PROMPT="$OUT_DIR/compact_prompt.txt"
python3 scripts/hugo_prompt_compact_from_claims.py --claims "$CLAIMS_JSON" --out "$COMPACT_PROMPT" --max-cards 8

GROK_MODEL="${GROK_MODEL:-gpt-5.2}"
GROK_TEMPERATURE="${GROK_TEMPERATURE:-0.7}"
export GROK_MODEL GROK_TEMPERATURE

# Draft generation (primary: cpa-plus; fallback: zai-coding-plan) — to survive CPA 429 rate limits.
PRIMARY_DRAFT_PROVIDER="${PRIMARY_DRAFT_PROVIDER:-cpa}"
FALLBACK_DRAFT_PROVIDER="${FALLBACK_DRAFT_PROVIDER:-zai}"
ZAI_MODEL="${ZAI_MODEL:-glm-5.1}"
ZAI_TEMPERATURE="${ZAI_TEMPERATURE:-0.7}"
ZAI_MAX_TOKENS="${ZAI_MAX_TOKENS:-2400}"

_draft_with_provider() {
  local provider="$1"
  if [[ "$provider" == "cpa" ]]; then
    python3 scripts/cpa_chat_completions.py \
      --model "$GROK_MODEL" \
      --system "You are a helpful assistant. Output only the final Chinese Markdown article." \
      --user-file "$COMPACT_PROMPT" \
      --temperature "$GROK_TEMPERATURE" \
      --max-tokens 2400 \
      --out "$ARTICLE_MD_RAW" \
      >/dev/null
  elif [[ "$provider" == "zai" ]]; then
    python3 scripts/zai_chat_completions.py \
      --model "$ZAI_MODEL" \
      --system "You are a helpful assistant. Output only the final Chinese Markdown article." \
      --user-file "$COMPACT_PROMPT" \
      --temperature "$ZAI_TEMPERATURE" \
      --max-tokens "$ZAI_MAX_TOKENS" \
      --out "$ARTICLE_MD_RAW" \
      >/dev/null
  else
    echo "Unknown draft provider: $provider" >&2
    return 2
  fi
}

# Try primary; if it fails (most commonly CPA 429), fallback once.
if _draft_with_provider "$PRIMARY_DRAFT_PROVIDER"; then
  :
else
  echo "WARN: drafting failed on provider=$PRIMARY_DRAFT_PROVIDER, trying fallback=$FALLBACK_DRAFT_PROVIDER" >&2
  _draft_with_provider "$FALLBACK_DRAFT_PROVIDER"
fi

ARTICLE_STATUS="generated"

# 2) Enforce final H1 title must be our secondary title (and must not equal source title)
STAGE="title_enforce"
python3 - <<'PY'
import os, pathlib, re
p = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
text = p.read_text(encoding='utf-8').strip('\n')
lines = text.splitlines()
our_title = (os.environ.get('TITLE') or '').strip()
source_title = (os.environ.get('SOURCE_TITLE') or '').strip()
if not our_title:
    raise SystemExit(0)
# Ensure our title differs from source
if our_title == source_title:
    our_title = our_title + '：我们真正该关注什么'

# Replace first H1 if present, otherwise prepend
idx = None
for i, ln in enumerate(lines[:40]):
    if re.match(r'^#\s+\S', ln):
        idx = i
        break

new_h1 = '# ' + our_title
if idx is None:
    lines = [new_h1, ''] + lines
else:
    lines[idx] = new_h1

p.write_text('\n'.join(lines).strip() + '\n', encoding='utf-8')
print('TITLE_OK')
PY

# 2b) Editor gate (LINUS by default): review and request one revision if needed
STAGE="edit_review"
EDITOR_AGENT="${EDITOR_AGENT:-linus}"
EDITOR_THRESHOLD="${EDITOR_THRESHOLD:-90}"
EDITOR_SESSION_ID="${HUGO_SESSION_ID}:editor"
EDITOR_JSON="$OUT_DIR/editor.json"
EDITOR_RAW="$OUT_DIR/editor_raw.json"
export EDITOR_AGENT EDITOR_THRESHOLD EDITOR_SESSION_ID EDITOR_JSON EDITOR_RAW

ARTICLE_TEXT=$(python3 - <<'PY'
import os, pathlib
p=pathlib.Path(os.environ['ARTICLE_MD_RAW'])
text=p.read_text(encoding='utf-8')
# cap for prompt size safety
print(text[:12000])
PY
)

if bash scripts/openclaw_cli.sh agent --agent "$EDITOR_AGENT" --session-id "$EDITOR_SESSION_ID" --to +15555550123 --timeout 600 --json --message "你现在是【公众号文章编辑/审稿人】。你不写文章，只审稿并给出修改意见。

文章二次标题：${TITLE}
源链接（仅用于判断是否雷同，不要输出链接到正文）：${URL}

正文（Markdown）：
${ARTICLE_TEXT}

请输出【严格 JSON】（不要 markdown，不要解释）：
{
  \"pass\": true,
  \"score\": 0,
  \"mustFix\": [\"必须修改点1\"],
  \"niceToHave\": [\"可选优化1\"],
  \"riskFlags\": [\"paraphrase\", \"templatey\", \"too_short\", \"logic_gap\", \"marketingy\"],
  \"rewriteBrief\": \"给作者(写作模型)的改稿指令，要求具体可执行\"
}

审稿重点：
- 是否像“改写新闻/复述源文”（段落顺序、措辞、信息组织）
- 标题和二级标题是否模板化
- 是否满足：≥3个原创结构件 + 读者任务
- 文内不得出现 URL/参考链接
- 逻辑是否完整、信息密度是否够、是否有可执行清单
" > "$EDITOR_RAW"; then
  python3 - <<'PY'
import json, os, pathlib, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.environ.get('SCRIPT_DIR','scripts')), 'scripts'))
from fix_json_quotes import fix_json_quotes

raw = pathlib.Path(os.environ['EDITOR_RAW']).read_text(encoding='utf-8')
lines = [l for l in raw.split('\n') if not l.startswith('[plugins]')]
clean = '\n'.join(lines)
start = clean.find('{')
obj = json.loads(clean[start:])

# unwrap openclaw agent wrapper
if 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
    if payloads:
        t = max(payloads, key=lambda p: len((p.get('text') or '').strip())).get('text') or ''
        t = t.strip()
        s = t.find('{')
        if s != -1:
            raw_json = t[s:]
            try:
                obj = json.loads(raw_json)
            except json.JSONDecodeError:
                try:
                    obj = json.loads(fix_json_quotes(raw_json))
                except Exception:
                    # salvage truncated JSON by cutting at last complete brace
                    last = raw_json.rfind('}')
                    if last != -1:
                        try:
                            obj = json.loads(raw_json[: last + 1])
                        except Exception:
                            obj = {'pass': False, 'score': 0, 'mustFix': ['editor_json_truncated'], 'niceToHave': [], 'riskFlags': ['editor_error'], 'rewriteBrief': ''}
                    else:
                        obj = {'pass': False, 'score': 0, 'mustFix': ['editor_json_invalid'], 'niceToHave': [], 'riskFlags': ['editor_error'], 'rewriteBrief': ''}

path = pathlib.Path(os.environ['EDITOR_JSON'])
path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('WROTE', str(path))
PY
else
  # If editor fails, do not block publish; just skip the gate.
  python3 - <<'PY' > "$EDITOR_JSON"
import json
print(json.dumps({'pass': True, 'score': 100, 'mustFix': [], 'niceToHave': [], 'riskFlags': [], 'rewriteBrief': ''}, ensure_ascii=False, indent=2))
PY
fi

# Apply up to N revisions (default 3)
MAX_REVISIONS="${MAX_REVISIONS:-3}"
export MAX_REVISIONS

rev=0
while true; do
  PASS=$(python3 - <<'PY'
import json, os
j=json.load(open(os.environ['EDITOR_JSON'],'r',encoding='utf-8'))
print('1' if j.get('pass') else '0')
PY
)
  SCORE=$(python3 - <<'PY'
import json, os
j=json.load(open(os.environ['EDITOR_JSON'],'r',encoding='utf-8'))
print(int(j.get('score') or 0))
PY
)
  BRIEF=$(python3 - <<'PY'
import json, os
j=json.load(open(os.environ['EDITOR_JSON'],'r',encoding='utf-8'))
print((j.get('rewriteBrief') or '').strip().replace('\n',' '))
PY
)

  if [[ "$PASS" == "1" && "$SCORE" -ge "$EDITOR_THRESHOLD" ]]; then
    break
  fi
  if [[ $rev -ge $MAX_REVISIONS ]]; then
    echo "WARN: editor_threshold_not_met score=$SCORE (continue to publish)" >&2
    break
  fi
  if [[ -z "${BRIEF:-}" ]]; then
    echo "WARN: missing_rewrite_brief score=$SCORE (continue to publish)" >&2
    break
  fi

  STAGE="edit_revise"
  rev=$((rev+1))

  # refresh article text snapshot for prompt
  ARTICLE_TEXT=$(python3 - <<'PY'
import pathlib, os
p=pathlib.Path(os.environ['ARTICLE_MD_RAW'])
text=p.read_text(encoding='utf-8')
print(text[:12000])
PY
)

  # Revision via direct Grok2API (stream=false)
  REV_PROMPT="$OUT_DIR/revise_prompt_${rev}.txt"
  export REV_PROMPT
  python3 - <<'PY' > "$REV_PROMPT"
import os, pathlib

title = os.environ.get('TITLE','').strip()
brief = os.environ.get('BRIEF','').strip()
article = pathlib.Path(os.environ['ARTICLE_MD_RAW']).read_text(encoding='utf-8')
article_excerpt = article[:12000]

ban_words = ['原创结构件','三层台阶','四层架构图','10项检查表','三问决策树','落地动作']

parts = []
parts.append('你现在要按编辑意见改稿。只输出最终可发布的中文 Markdown 正文：')
parts.append('- 必须以单个 H1 开头：# 标题')
parts.append('- 正文必须直接进入内容（禁止出现“分析/规划/提纲/草拟/检查/我将/下面开始”等元信息）')
parts.append('- 禁止出现任何 URL/参考链接')
parts.append('- 至少 5 个二级标题（##），且必须是问题式或结论式表达')
parts.append('- 必须包含：≥3 个结构件内容 + 1 段“读者任务”')
parts.append('- 语气：工程化、克制、有判断')
parts.append('- 禁止出现这些词：' + '、'.join(ban_words))
parts.append('')
parts.append(f'二次选题标题：{title}')
parts.append(f'编辑改稿指令（必须执行）：{brief}')
parts.append('')
parts.append('原稿（仅供你改写；不要照抄句式，不要保留任何元信息段落）：')
parts.append(article_excerpt)

print('\n'.join(parts))
PY

  # Revision generation (primary: cpa-plus; fallback: zai-coding-plan)
  PRIMARY_REV_PROVIDER="${PRIMARY_REV_PROVIDER:-${PRIMARY_DRAFT_PROVIDER:-cpa}}"
  FALLBACK_REV_PROVIDER="${FALLBACK_REV_PROVIDER:-${FALLBACK_DRAFT_PROVIDER:-zai}}"
  ZAI_MODEL="${ZAI_MODEL:-glm-5.1}"
  ZAI_TEMPERATURE="${ZAI_TEMPERATURE:-0.7}"
  ZAI_MAX_TOKENS="${ZAI_MAX_TOKENS:-2400}"

  _rev_with_provider() {
    local provider="$1"
    if [[ "$provider" == "cpa" ]]; then
      python3 scripts/cpa_chat_completions.py \
        --model "$GROK_MODEL" \
        --system "You are a helpful assistant. Output only the final Chinese Markdown article." \
        --user-file "$REV_PROMPT" \
        --temperature "$GROK_TEMPERATURE" \
        --max-tokens 2400 \
        --out "$ARTICLE_MD_RAW" \
        >/dev/null
    elif [[ "$provider" == "zai" ]]; then
      python3 scripts/zai_chat_completions.py \
        --model "$ZAI_MODEL" \
        --system "You are a helpful assistant. Output only the final Chinese Markdown article." \
        --user-file "$REV_PROMPT" \
        --temperature "$ZAI_TEMPERATURE" \
        --max-tokens "$ZAI_MAX_TOKENS" \
        --out "$ARTICLE_MD_RAW" \
        >/dev/null
    else
      echo "Unknown revision provider: $provider" >&2
      return 2
    fi
  }

  if _rev_with_provider "$PRIMARY_REV_PROVIDER"; then
    :
  else
    echo "WARN: revision failed on provider=$PRIMARY_REV_PROVIDER, trying fallback=$FALLBACK_REV_PROVIDER" >&2
    _rev_with_provider "$FALLBACK_REV_PROVIDER"
  fi

  # re-run editor on revised draft
  STAGE="edit_review"
  ARTICLE_TEXT=$(python3 - <<'PY'
import pathlib, os
p=pathlib.Path(os.environ['ARTICLE_MD_RAW'])
text=p.read_text(encoding='utf-8')
print(text[:12000])
PY
)

  if bash scripts/openclaw_cli.sh agent --agent "$EDITOR_AGENT" --session-id "$EDITOR_SESSION_ID" --to +15555550123 --timeout 600 --json --message "你现在是【公众号文章编辑/审稿人】。请复审修订稿，只输出严格 JSON，结构同前。

文章二次标题：${TITLE}
源链接：${URL}

正文（Markdown）：
${ARTICLE_TEXT}

输出 JSON：{\"pass\":true,\"score\":0,\"mustFix\":[],\"niceToHave\":[],\"riskFlags\":[],\"rewriteBrief\":\"...\"}
" > "$EDITOR_RAW"; then
    python3 - <<'PY'
import json, os, pathlib, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.environ.get('SCRIPT_DIR','scripts')), 'scripts'))
from fix_json_quotes import fix_json_quotes
raw = pathlib.Path(os.environ['EDITOR_RAW']).read_text(encoding='utf-8')
lines = [l for l in raw.split('\n') if not l.startswith('[plugins]')]
clean = '\n'.join(lines)
start=clean.find('{')
obj=json.loads(clean[start:])
if 'result' in obj and isinstance(obj.get('result'), dict):
    payloads=obj['result'].get('payloads') or []
    if payloads:
        t=max(payloads, key=lambda p: len((p.get('text') or '').strip())).get('text') or ''
        t=t.strip(); s=t.find('{')
        if s!=-1:
            try:
                obj=json.loads(t[s:])
            except json.JSONDecodeError:
                obj=json.loads(fix_json_quotes(t[s:]))
path=pathlib.Path(os.environ['EDITOR_JSON'])
path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print('WROTE', str(path))
PY
  else
    echo "WARN: editor re-review failed" >&2
    break
  fi
done

# 2c) Sanity check: never publish placeholder / too-short drafts
STAGE="sanity_check"
python3 - <<'PY'
import os, pathlib, re
p = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
text = p.read_text(encoding='utf-8')
plain = re.sub(r'```.*?```', '', text, flags=re.S)
plain = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', plain)
plain = re.sub(r'\s+', ' ', plain).strip()
# hard blocks
bad = [
  'Uh-oh, too much information',
  'sometimes less is more',
]
if any(b.lower() in plain.lower() for b in bad):
    raise SystemExit('bad_placeholder')
# minimum length (approx)
if len(plain) < 2000:
    raise SystemExit('too_short')
# should have some structure
if plain.count('##') == 0 and text.count('##') == 0:
    raise SystemExit('no_sections')
print('SANITY_OK')
PY

# 3) Generate in-article figures based on sections (best effort; do not block publish)
STAGE="figures"
FIGURE_STATUS="skipped"
FIGURE_COUNT="${FIGURE_COUNT:-3}"
FIGURE_PLAN_JSON="$OUT_DIR/figure_plan.json"
export OUT_DIR FIGURE_COUNT FIGURE_PLAN_JSON

# Extract candidate sections (## headings + first paragraph) for prompt generation
SECTIONS_TXT=$(python3 - <<'PY'
import os, pathlib, re
p = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
text = p.read_text(encoding='utf-8')
lines = text.splitlines()
sections=[]
cur=None
buf=[]
for ln in lines:
    m=re.match(r'^##\s+(.+)', ln)
    if m:
        if cur:
            cur['body']='\n'.join(buf).strip()
            sections.append(cur)
        cur={'heading':m.group(1).strip()}
        buf=[]
    else:
        if cur is not None:
            buf.append(ln)
if cur:
    cur['body']='\n'.join(buf).strip()
    sections.append(cur)

def first_para(md):
    # naive: first non-empty paragraph without headings/code
    md=re.sub(r'```.*?```','',md,flags=re.S)
    parts=[p.strip() for p in re.split(r'\n\s*\n', md) if p.strip()]
    for p in parts:
        if p.startswith('#') or p.startswith('![') or p.startswith('![]'):
            continue
        return re.sub(r'\s+',' ',p)[:220]
    return ''

out=[]
for s in sections:
    fp=first_para(s.get('body',''))
    if s['heading'] and fp:
        out.append((s['heading'], fp))

# fallback: no ## headings => use generic prompts
if not out:
    out=[('核心机制', '用一张图讲清核心机制与关键关系'),('落地路径', '用一张图讲清落地流程和关键节点'),('常见误区', '用一张图对比常见误区与正确做法')]

# print as numbered plain text
for i,(h,fp) in enumerate(out[:6],1):
    print(f"{i}) {h}\n   {fp}")
PY
)

# Ask an agent to generate image prompts (STRICT JSON)
FIGURE_AGENT="${FIGURE_AGENT:-linus}"
FIGURE_SESSION_ID="${HUGO_SESSION_ID}:figures"
export FIGURE_AGENT FIGURE_SESSION_ID

if bash scripts/openclaw_cli.sh agent --agent "$FIGURE_AGENT" --session-id "$FIGURE_SESSION_ID" --to +15555550123 --timeout 300 --json --message "你现在只做【配图提示词】生成，不写文章。

文章标题：${TITLE}
请基于下面的分段信息，为公众号文章生成 ${FIGURE_COUNT} 张【文内插图】提示词。

分段信息（每段：小标题 + 该段第一段内容摘要）：
${SECTIONS_TXT}

输出【严格 JSON】（不要 markdown）：
{
  \"figures\": [
    {
      \"index\": 1,
      \"afterHeading\": \"对应要插入在哪个二级标题(##)之后的标题文本\",
      \"prompt\": \"英文或中文都行，但必须清晰具体；必须强调无文字/无logo/无标识；画面要能支撑该段内容\"
    }
  ]
}

硬性要求：
- 每个 prompt 必须包含：no text, no letters, no numbers, no logo, no watermark
- 风格：干净的 editorial illustration / simplified diagram feel（但不要真的画可读文字）
- 构图：留白多、信息表达强
" > "$FIGURE_PLAN_JSON"; then
  # Generate images and inject into markdown
  if python3 - <<'PY'
import json, os, pathlib, re, subprocess, sys
# robust JSON repair for common LLM quoting bugs
sys.path.insert(0, os.path.join(os.path.dirname(os.environ.get('SCRIPT_DIR','scripts')), 'scripts'))
from fix_json_quotes import fix_json_quotes, parse_messy_json

out_dir = pathlib.Path(os.environ['OUT_DIR'])
md_path = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
plan_path = pathlib.Path(os.environ['FIGURE_PLAN_JSON'])
fig_n = int(os.environ.get('FIGURE_COUNT','3'))

raw = plan_path.read_text(encoding='utf-8')
start = raw.find('{')
try:
    obj = parse_messy_json(raw)
except Exception:
    obj = json.loads(fix_json_quotes(raw[start:]))

# unwrap openclaw wrapper
if 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
    if payloads:
        t = max(payloads, key=lambda p: len((p.get('text') or '').strip())).get('text') or ''
        t = t.strip()
        start2 = t.find('{')
        if start2 != -1:
            inner_raw = t[start2:]
            try:
                obj = json.loads(inner_raw)
            except json.JSONDecodeError:
                obj = json.loads(fix_json_quotes(inner_raw))

figs = obj.get('figures') or []
figs = figs[:fig_n]
if not figs:
    print('FIG_SKIP 0')
    raise SystemExit(0)

# Read markdown
text = md_path.read_text(encoding='utf-8')
lines = text.splitlines()

# helper: insert after a matching ## heading
inserts=[]  # (line_index, markdown_line)
for f in figs:
    idx = int(f.get('index') or 0)
    after = (f.get('afterHeading') or '').strip()
    prompt = (f.get('prompt') or '').strip()
    if not prompt:
        continue
    # enforce safety suffix
    if 'no text' not in prompt.lower():
        prompt += ' -- no text, no letters, no numbers, no logo, no watermark'

    png = out_dir / f"fig_{idx}.png"
    jpg = out_dir / f"fig_{idx}.jpg"

    # Do NOT force --model here. Let grok2api_image.sh pick provider-specific defaults
    # so SiliconFlow/BigModel fallbacks can switch models correctly.
    cmd = [
        'bash', os.path.expanduser('~/.openclaw/workspace-dali/scripts/grok2api_image.sh'),
        'generate', '--size', '1280x720', '--prompt', prompt, '--out', str(png)
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # convert to jpg for consistent upload
    subprocess.check_call(['ffmpeg','-y','-i',str(png),'-q:v','2',str(jpg)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # find insertion point
    insert_at = None
    if after:
        for i,ln in enumerate(lines):
            m=re.match(r'^##\s+(.+)', ln)
            if m and m.group(1).strip() == after:
                insert_at = i+1
                break
    if insert_at is None:
        # fallback: after first ##
        for i,ln in enumerate(lines):
            if ln.startswith('## '):
                insert_at = i+1
                break
    if insert_at is None:
        # fallback: after H1
        for i,ln in enumerate(lines):
            if ln.startswith('# '):
                insert_at = i+1
                break
    if insert_at is None:
        insert_at = 0

    inserts.append((insert_at, f"\n![](./{jpg.name})\n"))

# Apply inserts in reverse order
for at, md in sorted(inserts, key=lambda x:x[0], reverse=True):
    lines[at:at] = [md]

md_path.write_text('\n'.join(lines).strip() + '\n', encoding='utf-8')
print('FIG_OK', len(inserts))
PY
  then
    FIGURE_STATUS="ok"
  else
    FIGURE_STATUS="failed"
  fi
else
  FIGURE_STATUS="failed"
fi

# 4) Generate a cover image via DALI — best effort; fallback to default cover instead of blocking publish.
STAGE="cover"
COVER_SRC="$OUT_DIR/cover_src.png"
COVER_JPG="$OUT_DIR/cover.jpg"
DEFAULT_COVER="${DEFAULT_WECHAT_COVER:-$HOME/.openclaw/workspace/dali_cover_notext_v2.png}"
# Cover prompt can be overridden by nightly topic pack when available.
COVER_PROMPT_DEFAULT="Clean modern editorial illustration cover for a Chinese tech article. Bright optimistic palette, clean bold outlines, subtle sci‑fi, lots of empty space, no text, no letters, no numbers, no signage, no logos, no UI panels"
COVER_PROMPT="$COVER_PROMPT_DEFAULT"

# Prefer generating cover based on OUR final title
if [[ -n "${TITLE:-}" ]]; then
  COVER_PROMPT="Cover image for a Chinese WeChat tech article titled: ${TITLE}. Modern editorial illustration, symbolic scene matching the title, clean composition, generous whitespace, no text, no letters, no numbers, no logos, no watermarks"
fi

if [[ "${USE_NIGHTLY_PACK:-1}" == "1" ]] && [[ -f "${NIGHTLY_PACK_JSON:-rss/nightly_pack.json}" ]]; then
  PACK_COVER_PROMPT=$(python3 - <<'PY'
import json, os
pack_path = os.environ.get('NIGHTLY_PACK_JSON', 'rss/nightly_pack.json')
url = os.environ.get('URL','').strip()
try:
    pack = json.load(open(pack_path,'r',encoding='utf-8'))
except Exception:
    pack = None
if not pack or not isinstance(pack, dict):
    print('')
    raise SystemExit(0)
items = pack.get('items') or []
item = None
for it in items:
    if (it.get('url') or '').strip() and url and (it.get('url') or '').strip()==url:
        item = it
        break
if not item and items:
    item = items[0]
cp = (item.get('coverPrompt') or '').strip() if item else ''
print(cp)
PY
)
  if [[ -n "${PACK_COVER_PROMPT}" ]]; then
    COVER_PROMPT="$PACK_COVER_PROMPT"
  fi
fi
COVER_STATUS="generated"

# Do NOT force --model here. Let grok2api_image.sh pick provider-specific defaults
# so SiliconFlow/BigModel fallbacks can switch models correctly.
if ! bash "$HOME/.openclaw/workspace-dali/scripts/grok2api_image.sh" generate \
  --size 1792x1024 \
  --prompt "$COVER_PROMPT" \
  --out "$COVER_SRC" \
  >/dev/null 2>&1; then
  COVER_STATUS="default"
fi

if [[ "$COVER_STATUS" == "generated" ]] && [[ -f "$COVER_SRC" ]]; then
  if ! ffmpeg -y -i "$COVER_SRC" -vf "scale=1080:864:force_original_aspect_ratio=increase,crop=1080:864" -q:v 2 "$COVER_JPG" >/dev/null 2>&1; then
    COVER_STATUS="default"
  fi
else
  COVER_STATUS="default"
fi

if [[ "$COVER_STATUS" == "default" ]]; then
  if [[ -f "$DEFAULT_COVER" ]]; then
    cp "$DEFAULT_COVER" "$COVER_JPG"
  else
    echo "Cover generation failed and default cover missing: $DEFAULT_COVER" >&2
    exit 3
  fi
fi

# 3) Wrap article with frontmatter for wechat-publisher
FINAL_MD="$OUT_DIR/article.md"
export FINAL_MD
python3 - <<'PY'
import pathlib, os, re, json

article_md_raw = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
final_md = pathlib.Path(os.environ['FINAL_MD'])
raw = article_md_raw.read_text(encoding='utf-8')

MAXLEN = int(os.environ.get('WECHAT_TITLE_MAXLEN', '32'))


def has_cjk(s: str) -> bool:
    return any('\u4e00' <= ch <= '\u9fff' for ch in s)


def clean_title(t: str) -> str:
    t = (t or '').strip()
    t = re.sub(r'https?://\S+', '', t).strip()
    t = re.sub(r'\s+', ' ', t).strip()

    # Drop common author/source suffixes
    for sep in ['｜', '|']:
        if sep in t:
            t = t.split(sep)[0].strip()

    # Prefer the clause after colon if it is Chinese and short enough
    candidates = [t]
    for sep in ['：', ':', '—', '-', '–']:
        if sep in t:
            candidates.append(t.split(sep)[-1].strip())

    for c in candidates:
        if c and len(c) <= MAXLEN and has_cjk(c):
            return c

    if not t:
        return '今日科技科普'

    if len(t) > MAXLEN:
        t = t[:MAXLEN].rstrip()
    return t


# 1) Try to use our curated title from title.json (二次选题), then env TITLE, then H1.
title_from_json = ''
try:
    p = os.environ.get('TITLE_JSON')
    if p and pathlib.Path(p).exists():
        obj = json.load(open(p, 'r', encoding='utf-8'))
        title_from_json = (obj.get('title') or '').strip()
except Exception:
    title_from_json = ''

title_env = (os.environ.get('TITLE') or '').strip()

h1 = ''
if raw.strip().startswith('#'):
    h1 = raw.splitlines()[0].lstrip('# ').strip()

chosen = title_from_json or title_env or h1 or '今日科技科普'
fm_title = clean_title(chosen)

fm = '---\n'
fm += f"title: {fm_title}\n"
fm += 'cover: ./cover.jpg\n'
fm += '---\n\n'
final_md.write_text(fm + raw + '\n', encoding='utf-8')
print('WROTE', str(final_md), 'title_len', len(fm_title))
PY

# 4) Publish to WeChat drafts
STAGE="wechat_publish"
WECHAT_MEDIA_ID="${WECHAT_MEDIA_ID:-}"
if [[ "${NOTION_ONLY:-0}" != "1" ]]; then
  WECHAT_PUBLISH_LOG="$OUT_DIR/wechat_publish.log"
  export WECHAT_PUBLISH_LOG
  bash "$HOME/.openclaw/workspace/skills/wechat-publisher/scripts/publish.sh" "$FINAL_MD" lapis solarized-light | tee "$WECHAT_PUBLISH_LOG"

  WECHAT_MEDIA_ID=$(python3 - <<'PY'
import os, re, pathlib
p = pathlib.Path(os.environ['WECHAT_PUBLISH_LOG'])
text = p.read_text(encoding='utf-8') if p.exists() else ''
m = re.search(r'Media ID:\s*([A-Za-z0-9_\-]+)', text)
print(m.group(1) if m else '')
PY
)
fi

# 4b) Auto-cleanup is handled by the global trap (see top of file)

# 5) Sync to Notion for mobile reading — best effort; failure should not block WeChat draft delivery.
STAGE="notion_sync"
NOTION_ARTICLE_DATABASE_ID="${NOTION_ARTICLE_DATABASE_ID:-3188bd97-88dd-8034-ae05-d4c7f2b4b10e}"
NOTION_SYNC_LOG="$OUT_DIR/notion_sync.json"
NOTION_SYNC_STATUS="ok"
if ! python3 "$HOME/.openclaw/workspace/scripts/markdown_to_notion_page.py" \
  --md "$FINAL_MD" \
  --database-id "$NOTION_ARTICLE_DATABASE_ID" \
  --source-url "$URL" \
  --topic "$TITLE" \
  --wechat-media-id "$WECHAT_MEDIA_ID" | tee "$NOTION_SYNC_LOG"; then
  NOTION_SYNC_STATUS="failed"
  echo "WARN: Notion sync failed; see $NOTION_SYNC_LOG" >&2
fi

# 6) Publish to Halo (direct) — best effort; do NOT block earlier deliveries.
# Default: DISABLED to avoid creating "bad drafts" (Halo console 500: snapshot is not a base snapshot).
# Enable explicitly by setting: HALO_ENABLE=1
STAGE="halo_publish"
HALO_SYNC_STATUS="skipped"
HALO_PUBLISH_LOG="$OUT_DIR/halo_publish.json"
export HALO_PUBLISH_LOG

# Prefer raw md (no wechat frontmatter)
if [[ "${HALO_ENABLE:-0}" == "1" ]] && [[ -n "${HALO_BASE_URL:-}" ]] && [[ -n "${HALO_TOKEN:-}" ]]; then
  HALO_SYNC_STATUS="ok"
  if ! python3 "$HOME/.openclaw/workspace/scripts/halo_publish_post.py" \
    --md "$ARTICLE_MD_RAW" \
    --category "公众号" \
    --tag tech \
    > "$HALO_PUBLISH_LOG"; then
    HALO_SYNC_STATUS="failed"
    echo "WARN: Halo publish failed; see $HALO_PUBLISH_LOG" >&2
  fi
fi

STAGE="done"
echo "MORNING_OK title=$TITLE url=$URL out=$OUT_DIR media_id=$WECHAT_MEDIA_ID web_research_status=$WEB_RESEARCH_STATUS article_status=$ARTICLE_STATUS cover_status=$COVER_STATUS notion_status=$NOTION_SYNC_STATUS halo_status=$HALO_SYNC_STATUS"
