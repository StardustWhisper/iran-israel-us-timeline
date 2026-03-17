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

TITLE=$(python3 - <<'PY'
import json
p='$BRIEF'
d=json.load(open(p,'r',encoding='utf-8'))
print(d['top']['title'])
PY
)
URL=$(python3 - <<'PY'
import json
p='$BRIEF'
d=json.load(open(p,'r',encoding='utf-8'))
print(d['top']['url'])
PY
)

DATE_DIR=$(date +%Y%m%d)
OUT_DIR="$HOME/.openclaw/workspace/wechat-publisher-out/auto/$DATE_DIR"
mkdir -p "$OUT_DIR"

# 1) Let HUGO write article (markdown) based on topic + URL (grounding is handled by HUGO prompt; we include the URL for reference)
ARTICLE_JSON="$OUT_DIR/hugo.json"
ARTICLE_MD_RAW="$OUT_DIR/article_raw.md"
export ARTICLE_JSON ARTICLE_MD_RAW

bash scripts/openclaw_cli.sh agent --agent hugo --to +15555550123 --timeout 600 --json --message "写一篇科技公众号科普文章，主题来自热点：\n\n标题建议围绕：${TITLE}\n参考链接（仅作为事实边界，不要编造具体数字）：${URL}\n\n要求：\n- 受众：懂一点科技的普通读者\n- 结构：抓人开头→发生了什么→核心机制讲解(3-5点)→常见误区→结论&关注信号\n- 风格：口语但不油腻，信息密度高\n- 长度：1800-2400字\n- 末尾加‘参考阅读’列出上述链接\n- 另外输出：封面图提示词（无文字版）3个备选（英文prompt+negative，强调 no text）\n" > "$ARTICLE_JSON"

python3 - <<'PY'
import json, pathlib, os
article_json = pathlib.Path(os.environ['ARTICLE_JSON'])
article_md_raw = pathlib.Path(os.environ['ARTICLE_MD_RAW'])
content = article_json.read_text(encoding='utf-8')
# openclaw_cli.sh may emit non-JSON log lines before the JSON payload (e.g. plugin registration).
start = content.find('{')
if start == -1:
    raise SystemExit('No JSON object found in ' + str(article_json))
obj = json.loads(content[start:])
text = obj['result']['payloads'][0].get('text', '').strip()
article_md_raw.write_text(text + '\n', encoding='utf-8')
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
