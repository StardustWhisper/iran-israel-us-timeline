#!/usr/bin/env python3
"""Select top topic from RSS items and produce a brief for HUGO.

Inputs:
- items JSON from rss_radar_fetch.py
Outputs:
- brief JSON to stdout or file

Scoring is heuristic (no web fetch):
- Prefer AI/compute/agent topics for now
- Prefer explanatory potential and visualizability
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

AI_KW = [
    (r"\bAI\b|人工智能|大模型|模型|LLM|多模态|Agent|智能体", 4.0),
    (r"芯片|GPU|算力|推理|训练|数据中心|GTC|英伟达|NVIDIA", 3.0),
    (r"安全|越狱|提示注入|prompt injection|对齐|红队", 2.0),
    (r"机器人|自动驾驶|出行|eVTOL|低空", 2.0),
    (r"硬件|终端|眼镜|手机|PC", 1.5),
]
PENALTY_KW = [
    (r"股价|暴跌|监管约谈|财报|融资报告", 1.0),
    (r"明星八卦|娱乐", 2.0),
]


def score(title: str) -> float:
    s = 0.0
    for pat, w in AI_KW:
        if re.search(pat, title, re.I):
            s += w
    for pat, w in PENALTY_KW:
        if re.search(pat, title, re.I):
            s -= w
    # prefer shorter, punchier
    s -= max(0, (len(title) - 30)) * 0.02
    return s


def score_item(it: dict) -> float:
    title = it.get("title", "") or ""
    s = score(title)

    # GitHub is auxiliary (AI/LLM trending signal). Apply heavy downweight so it won't dominate media headlines.
    if it.get("kind") == "github":
        s *= 0.35
        stars = int(it.get("stars") or 0)
        # Small popularity nudge (still downweighted overall)
        s += math.log10(max(1, stars)) * 0.3
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--extra", action="append", default=[], help="extra items json (same schema: {items:[...]})")
    ap.add_argument("--out")
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    items = list(data.get("items") or [])

    for extra_path in args.extra:
        try:
            extra = json.loads(Path(extra_path).read_text(encoding="utf-8"))
            items.extend(extra.get("items") or [])
        except Exception:
            pass

    for it in items:
        it["score"] = round(float(score_item(it)), 3)

    items_sorted = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    top = items_sorted[0] if items_sorted else None

    brief = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": sorted({(it.get('sourceBlog') or it.get('source') or data.get('blog') or 'unknown') for it in items}),
        "top": top,
        "top10": items_sorted[:10],
        "hugoBrief": None,
    }

    if top:
        brief["hugoBrief"] = {
            "topic": top["title"],
            "angle": "科技科普：把新闻事件背后的技术/产业逻辑讲透，少八卦多机制；给普通读者可理解的类比与结论。",
            "structure": [
                "一句话抓人开头（从读者视角的疑问/误解切入）",
                "发生了什么（30秒看懂）",
                "为什么重要（对行业/普通人意味着什么）",
                "核心机制讲解（3-5点）",
                "常见误区/容易被误导的点",
                "结论+可执行建议（关注哪些信号）",
            ],
            "constraints": [
                "不编造未在来源中出现的具体数字/公司细节；不确定则用‘可能/通常/一般’表述",
                "给出配图脚本（无文字）",
            ],
        }

    out = json.dumps(brief, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)


if __name__ == "__main__":
    main()
