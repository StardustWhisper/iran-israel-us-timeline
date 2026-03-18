#!/usr/bin/env bash
set -euo pipefail

# Morning: use last night's brief -> ask HUGO to draft -> generate cover -> publish to WeChat drafts
# This script is designed to be run under OpenClaw cron via exec.

cd "$HOME/.openclaw/workspace"

set -a
source "$HOME/.openclaw/.env" 2>/dev/null || true
set +a

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

TITLE=$(python3 - <<'PY'
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
OUT_DIR="$HOME/.openclaw/workspace/wechat-publisher-out/auto/$DATE_DIR"
mkdir -p "$OUT_DIR"

# 1) Build research briefs so HUGO can synthesize, not merely rewrite the source link.
RESEARCH_JSON="$OUT_DIR/research.json"
WEB_RESEARCH_RAW="$OUT_DIR/web_research_raw.json"
WEB_RESEARCH_JSON="$OUT_DIR/web_research.json"
export RESEARCH_JSON WEB_RESEARCH_RAW WEB_RESEARCH_JSON

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

# 1a) Ask an agent to do lightweight web research and return STRICT JSON only.
bash scripts/openclaw_cli.sh agent --agent hugo --to +15555550123 --timeout 600 --json --message "你现在不是写文章，而是在做选题研究。请使用联网搜索，围绕下面这个主题补充 3-6 条高质量资料，优先官方来源、主流科技媒体、研究机构。

主题：${TITLE}
主参考链接：${URL}

要求：
- 目标：帮助后续写作，不要只重复主参考链接内容
- 必须主动搜索并综合资料，补充背景、机制、行业语境、争议或误区
- 只输出一个 JSON 对象，不要输出任何额外说明、markdown 代码块或前言
- JSON 结构必须是：
{
  \"summary\": [\"要点1\", \"要点2\", \"要点3\"],
  \"sources\": [
    {\"title\": \"标题\", \"url\": \"链接\", \"type\": \"official|media|research|analysis\", \"note\": \"这条材料能补充什么\"}
  ],
  \"angles\": [\"可展开角度1\", \"可展开角度2\"]
}
- `sources` 里尽量不要重复主参考链接
- 如果某条信息把握不大，就不要写进 summary
" > "$WEB_RESEARCH_RAW"

python3 scripts/rss_web_research_normalize.py \
  --in "$WEB_RESEARCH_RAW" \
  --out "$WEB_RESEARCH_JSON" \
  --title "$TITLE" \
  --source-url "$URL"

RESEARCH_BRIEF=$(python3 - <<'PY'
import json, os
rss_p = os.path.expanduser(os.environ['RESEARCH_JSON'])
web_p = os.path.expanduser(os.environ['WEB_RESEARCH_JSON'])
rss = json.load(open(rss_p, 'r', encoding='utf-8'))
web = json.load(open(web_p, 'r', encoding='utf-8'))
lines = []
lines.append(f"选题模板：{rss.get('template') or 'general-tech'}")
lines.append('补充资料（来自当前 RSS 候选池，可用于拓展背景，不要逐条照抄）：')
for i, it in enumerate(rss.get('related') or [], 1):
    lines.append(f"{i}. [{it.get('source')}] {it.get('title')} — {it.get('url')}")
if web.get('summary') or web.get('sources') or web.get('angles'):
    lines.append('')
    lines.append('外部 research 摘要（通过联网搜索整理，可用于补强文章深度）：')
    lines.append(f"- 质量检查：{'通过' if web.get('qualityOk') else '偏弱，尽量保守写作'}")
    for i, s in enumerate(web.get('summary') or [], 1):
        lines.append(f"- 要点{i}：{s}")
    if web.get('angles'):
        lines.append('- 可展开角度：' + '；'.join(web.get('angles')))
    for i, src in enumerate(web.get('sources') or [], 1):
        lines.append(f"{i}. [{src.get('type','source')}] {src.get('title')} — {src.get('url')}")
        note = (src.get('note') or '').strip()
        if note:
            lines.append(f"   用途：{note}")
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

# 2) Let HUGO write article (markdown) based on topic + source URL + RSS/web research materials.
ARTICLE_JSON="$OUT_DIR/hugo.json"
ARTICLE_MD_RAW="$OUT_DIR/article_raw.md"
export ARTICLE_JSON ARTICLE_MD_RAW RESEARCH_JSON WEB_RESEARCH_JSON

bash scripts/openclaw_cli.sh agent --agent hugo --to +15555550123 --timeout 600 --json --message "请直接写一篇可发布到微信公众号的科技科普文章。\n\n主题：${TITLE}\n主参考链接（仅作为事实边界，不要编造具体数字）：${URL}\n\n${RESEARCH_BRIEF}\n\n硬性要求：\n- 最终输出必须是【可直接发表的正文 Markdown】\n- 不要输出任何写作说明、提示词、封面建议、编者按、备注、TODO、附加解释\n- 不要出现‘以下是文章’‘可直接发布’‘供你参考’之类的前言\n- 只输出文章本身\n- 不要只改写主参考链接，要综合 RSS 补充资料和外部 research，提炼更完整的背景、机制和产业语境\n- 如果外部 research 质量偏弱，就保守吸收，只把确定性高的内容写进正文\n- 如果补充资料与主参考链接角度不同，可以用于解释上下文，但不要编造它们没有明确支持的事实\n- 受众：懂一点科技的普通读者\n- ${ARTICLE_STRUCTURE}\n- 风格：口语但不油腻，信息密度高\n- 长度：1800-2400字\n- 文末加‘参考阅读’，至少包含主参考链接；若正文确实吸收了补充资料，也可列出 2-5 条最相关链接\n" > "$ARTICLE_JSON"

python3 - <<'PY'
import json, pathlib, os, re
article_json = pathlib.Path(os.environ['ARTICLE_JSON'])
article_md_raw = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
content = article_json.read_text(encoding='utf-8')
# openclaw_cli.sh may emit non-JSON log lines before the JSON payload (e.g. plugin registration).
start = content.find('{')
if start == -1:
    raise SystemExit('No JSON object found in ' + str(article_json))
obj = json.loads(content[start:])
text = obj['result']['payloads'][0].get('text', '').strip()
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

# 2) Generate a cover image via DALI (grok2api) — no text
COVER_SRC="$OUT_DIR/cover_src.png"
COVER_JPG="$OUT_DIR/cover.jpg"
COVER_PROMPT="Clean modern editorial illustration cover for a Chinese tech article about AI agents and inference compute. Bright optimistic palette, clean bold outlines, cel shading, futuristic city datacenter + agent icons, lots of empty space, no text, no letters, no numbers, no signage, no logos, no UI panels"

bash "$HOME/.openclaw/workspace-dali/scripts/grok2api_image.sh" generate \
  --model grok-imagine-1.0 \
  --size 1792x1024 \
  --prompt "$COVER_PROMPT" \
  --out "$COVER_SRC" \
  >/dev/null

# Resize/crop to 1080x864 (wenyan cover preference) and convert to jpg
ffmpeg -y -i "$COVER_SRC" -vf "scale=1080:864:force_original_aspect_ratio=increase,crop=1080:864" -q:v 2 "$COVER_JPG" >/dev/null 2>&1

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
bash "$HOME/.openclaw/workspace/skills/wechat-publisher/scripts/publish.sh" "$FINAL_MD" lapis solarized-light

echo "DRAFT_OK title=$TITLE url=$URL out=$OUT_DIR"
