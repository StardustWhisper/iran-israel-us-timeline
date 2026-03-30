#!/usr/bin/env python3
"""Build a compact WeChat-article prompt from claims.json.

The goal is to reduce prompt size and avoid templatey headings.

Usage:
  python3 scripts/hugo_prompt_compact_from_claims.py \
    --claims /path/claims.json \
    --out /path/prompt.txt
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-cards", type=int, default=8)
    args = ap.parse_args()

    d = json.loads(Path(args.claims).read_text(encoding="utf-8"))
    title = (d.get("topic") or "企业AI为什么上不了生产").strip()
    thesis = (d.get("thesis") or "").strip()

    cards = (d.get("cards") or [])[: max(0, args.max_cards)]
    card_lines = []
    for i, c in enumerate(cards, 1):
        claim = (c.get("claim") or "").strip()
        conf = (c.get("confidence") or "").strip()
        if claim:
            card_lines.append(f"{i}. ({conf}) {claim}")

    comps = d.get("originalComponents") or []
    comps = [str(x).strip() for x in comps if str(x).strip()][:3]

    rules = d.get("antiParaphraseRules") or []
    rules = [str(x).strip() for x in rules if str(x).strip()][:4]

    ban_words = ["原创结构件", "三层台阶", "四层架构图", "10项检查表", "三问决策树", "落地动作"]

    parts = []
    parts.append("你现在要写一篇可发布到微信公众号的中文专栏文章（不要附参考链接，不要出现任何URL）。")
    parts.append("")
    parts.append(f"标题（尽量精炼，全文‘：’最多出现一次）：{title}")
    if thesis:
        parts.append(f"一句话主张（写进开头）：{thesis}")
    parts.append("")
    parts.append("只能使用下面这些【观点卡片】组织文章论述（不要复述新闻原文段落顺序；不要空话）：")
    parts.append("\n".join(card_lines) if card_lines else "(无卡片)")
    parts.append("")
    parts.append("必须隐含落地的3个结构件（内容要出现，但标题不要用标签词）：")
    for s in comps:
        parts.append("- " + s)
    parts.append("")
    parts.append("反复述规则（必须遵守，目标是写出‘主题驱动’原创专栏，而不是改写某篇文章）：")
    for s in rules:
        parts.append("- " + s)
    parts.append("")
    parts.append("硬性要求：")
    parts.append("- 二级标题(##)必须是自然的问题式/结论式表达，禁止出现这些词：" + "、".join(ban_words))
    parts.append("- 至少包含1段‘读者任务’（让读者回到自己团队做一个小动作）")
    parts.append("- 至少包含3个可执行清单/检查点（要具体到动作/字段/日志/权限）；其中至少1个清单必须是你自创的框架（不是来源文章里的列表）")
    parts.append("- 语气：工程化、克制、有判断；不要营销语、不要口号")
    parts.append("- 长度：1800-2400字")
    parts.append("")
    parts.append("输出：仅输出正文Markdown（以# 标题开头），不要解释。")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
