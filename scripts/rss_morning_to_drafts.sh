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

on_error() {
  local exit_code=$?
  echo "MORNING_FAIL stage=$STAGE web_research_status=$WEB_RESEARCH_STATUS article_status=$ARTICLE_STATUS cover_status=$COVER_STATUS notion_status=$NOTION_SYNC_STATUS media_id=$WECHAT_MEDIA_ID" >&2
  exit "$exit_code"
}
trap on_error ERR

BRIEF="rss/brief.json"
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
print(d['top']['title'])
PY
)
URL=$(python3 - <<'PY'
import json, os
p=os.environ['BRIEF']
d=json.load(open(p,'r',encoding='utf-8'))
print(d['top']['url'])
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
STAGE="title"
TITLE_JSON="$OUT_DIR/title.json"
export SOURCE_TITLE URL TITLE_JSON
TITLE=$(bash scripts/openclaw_cli.sh agent --agent hugo --to +15555550123 --timeout 300 --json --message "你现在做【二次选题】。我会给你：源标题 + 源链接 + 目标平台（公众号）。

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

if ! bash scripts/openclaw_cli.sh agent --agent hugo --to +15555550123 --timeout 900 --json --message "你现在不是写文章，而是在搭建【观点卡片（Claim Cards）】。

输入：
- 二次选题标题：${TITLE}
- 一句话观点（thesis）：$(python3 - <<'PY'
import json, os
p=os.environ.get('TITLE_JSON','')
if p and os.path.exists(p):
    t=open(p,'r',encoding='utf-8').read(); s=t.find('{'); obj=json.loads(t[s:])
    if 'result' in obj and isinstance(obj.get('result'), dict):
        payloads=obj['result'].get('payloads') or []
        if payloads:
            inner=(payloads[0].get('text') or '').strip(); i=inner.find('{')
            if i!=-1:
                try: obj=json.loads(inner[i:])
                except: pass
    print((obj.get('thesis') or '').strip())
PY
)
- 源标题（仅供定位）：${SOURCE_TITLE}
- 主参考链接（仅作为事实边界，可浏览但不要照抄）：${URL}

任务：
1) 联网搜索并阅读多方资料（尽量跨 2-3 个来源，允许多语种），把你准备在文中主张的观点拆成 8-12 张卡片。
2) 每张卡片必须可写成一句“主张句”，并带 1-3 条证据来源（只做内部支撑，最终文章不要放链接）。
3) 给出 3 个“原创结构件”，用于让文章明显不像新闻复述（例如：检查表、分层模型、决策树、对比表、上线守则）。

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
else
  # Normalize claims JSON: unwrap openclaw wrapper and keep only the inner object
  python3 - <<'PY'
import json, os, pathlib
raw_path = pathlib.Path(os.environ['CLAIMS_RAW'])
out_path = pathlib.Path(os.environ['CLAIMS_JSON'])
text = raw_path.read_text(encoding='utf-8')
start = text.find('{')
obj = json.loads(text[start:])
if 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
    if payloads:
        inner = (max(payloads, key=lambda p: len((p.get('text') or '').strip())).get('text') or '').strip()
        start2 = inner.find('{')
        if start2 != -1:
            obj = json.loads(inner[start2:])
obj['qualityOk'] = bool(obj.get('cards'))
out_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('WROTE', str(out_path))
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
import os
m = os.environ.get('TOPIC_TEMPLATE', 'general-tech')
if m == 'security':
    print('结构：抓人开头→什么是这类风险→为什么现在更值得关注→典型攻击/失误路径→工程上怎么防→普通团队现在该做什么→结论')
elif m == 'agent-industry':
    print('结构：抓人开头→发生了什么→这句话真正指向什么→为什么 Agent 会冲击现有软件形态→哪些环节不会被取代→对创业公司和普通用户意味着什么→结论')
elif m == 'compute-industry':
    print('结构：抓人开头→发生了什么→为什么算力/推理成为核心矛盾→背后的技术和产业机制→常见误区→接下来值得关注什么→结论')
else:
    print('结构：抓人开头→发生了什么→核心机制讲解(3-5点)→常见误区→结论&关注信号')
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

if ! bash scripts/openclaw_cli.sh agent --agent hugo --to +15555550123 --timeout 900 --json --message "请直接写一篇可发布到微信公众号的科技科普文章（不要贴参考链接）。

二次选题标题（必须用这个，不要用源标题）：${TITLE}
文章核心观点（一句话，可写进开头）：${THESIS}
源标题（禁止照抄/禁止做同义改写标题）：${SOURCE_TITLE}
主参考链接（仅作为事实边界，不要按其段落顺序复述）：${URL}

${RESEARCH_BRIEF}

关键要求：
- 你写作时【只允许】使用“观点卡片（Claim Cards）”组织正文的论述；不要复述源文章段落顺序。
- 正文必须显式包含至少 3 个“原创结构件”（检查表/分层模型/决策树/对比表/上线守则等），并且要能让读者照着执行。
- 必须包含 1 段“读者任务”（让读者回到自己系统/团队，做一个小的可执行动作）。

硬性要求（来自 Lambda）：
1) 标题一定不能和源标题一样。
2) 二次选题：在推荐标题基础上形成自己的观点（要写出明确判断/取舍）。
3) 根据二次选题标题，再次收集信息完成文章：必须综合多方资料，不要只改写主参考链接。
4) 推送到公众号的文章不必附加参考链接：不要在文末添加‘参考阅读/参考链接’段落，也不要在正文中放 URL。
5) 封面图以标题为主（这一点你不用输出提示词）。
6) 文内插图根据段落生成（这一点你不用输出提示词）。

写作要求：
- 最终输出必须是【可直接发表的正文 Markdown】
- 不要输出任何写作说明、提示词、封面建议、编者按、备注、TODO、附加解释
- 只输出文章本身
- 受众：懂一点科技的普通读者
- ${ARTICLE_STRUCTURE}
- 风格：口语但不油腻，信息密度高
- 长度：1800-2400字
" > "$ARTICLE_JSON"; then
  ARTICLE_STATUS="reused"
else
  if python3 - <<'PY'
import json, pathlib, os, re
article_json = pathlib.Path(os.environ['ARTICLE_JSON'])
article_md_raw = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
content = article_json.read_text(encoding='utf-8')

start = content.find('{')
if start == -1:
    raise SystemExit('No JSON object found in ' + str(article_json))
obj = json.loads(content[start:])

text = ''
if isinstance(obj, dict) and 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
    if payloads and isinstance(payloads, list):
        # Prefer the LONGER payload (some agents send a short partial first)
        best = max(payloads, key=lambda p: len((p.get('text') or '').strip()))
        text = (best.get('text') or '').strip()
elif isinstance(obj, dict) and 'payloads' in obj:
    payloads = obj.get('payloads') or []
    if payloads and isinstance(payloads, list):
        best = max(payloads, key=lambda p: len((p.get('text') or '').strip()))
        text = (best.get('text') or '').strip()

if not text:
    raise KeyError(f"No text payload found. top_keys={list(obj.keys())}")

# Strip common prefaces
patterns = [
    r'^以下是.*?\n+',
    r'^下面是.*?\n+',
    r'^当然可以.*?\n+',
    r'^这是一篇.*?\n+',
    r'^#?\s*可直接发布.*?\n+',
]
for pat in patterns:
    text = re.sub(pat, '', text, flags=re.S)

article_md_raw.write_text(text.strip() + '\n', encoding='utf-8')
print('WROTE', str(article_md_raw))
PY
  then
    ARTICLE_STATUS="generated"
  elif [[ -s "$ARTICLE_MD_RAW" ]]; then
    ARTICLE_STATUS="reused"
  else
    echo "Article generation failed and no reusable raw draft found" >&2
    exit 4
  fi
fi

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

# Ask HUGO to generate image prompts (STRICT JSON)
if bash scripts/openclaw_cli.sh agent --agent hugo --to +15555550123 --timeout 300 --json --message "你现在只做【配图提示词】生成，不写文章。

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
import json, os, pathlib, re, subprocess
out_dir = pathlib.Path(os.environ['OUT_DIR'])
md_path = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
plan_path = pathlib.Path(os.environ['FIGURE_PLAN_JSON'])
fig_n = int(os.environ.get('FIGURE_COUNT','3'))

raw = plan_path.read_text(encoding='utf-8')
start = raw.find('{')
obj = json.loads(raw[start:])
# unwrap openclaw wrapper
if 'result' in obj and isinstance(obj.get('result'), dict):
    payloads = obj['result'].get('payloads') or []
    if payloads:
        t = (payloads[0].get('text') or '').strip()
        start2 = t.find('{')
        if start2 != -1:
            obj = json.loads(t[start2:])

figs = obj.get('figures') or []
figs = figs[:fig_n]
if not figs:
    raise SystemExit('no figures')

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

    cmd = [
        'bash', os.path.expanduser('~/.openclaw/workspace-dali/scripts/grok2api_image.sh'),
        'generate', '--model', 'grok-imagine-1.0', '--size', '1280x720', '--prompt', prompt, '--out', str(png)
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

if ! bash "$HOME/.openclaw/workspace-dali/scripts/grok2api_image.sh" generate \
  --model grok-imagine-1.0 \
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
import pathlib, os
article_md_raw = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
final_md = pathlib.Path(os.environ['FINAL_MD'])
raw = article_md_raw.read_text(encoding='utf-8')
fm = '---\n'
fm += f"title: {raw.splitlines()[0].lstrip('# ').strip() if raw.strip().startswith('#') else '今日科技科普'}\n"
fm += 'cover: ./cover.jpg\n'
fm += '---\n\n'
final_md.write_text(fm + raw + '\n', encoding='utf-8')
print('WROTE', str(final_md))
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
