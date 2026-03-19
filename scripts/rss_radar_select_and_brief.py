#!/usr/bin/env python3
"""Select top topic from RSS items and produce a brief for HUGO.

Inputs:
- items JSON from rss_radar_fetch.py
Outputs:
- brief JSON to stdout or file

Scoring is heuristic with novelty penalties:
- Prefer AI/compute/agent topics for now
- Prefer explanatory potential and visualizability
- Penalize topics too similar to recently drafted/published article titles
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

STOPWORDS = {
    "的", "了", "和", "与", "及", "或", "在", "是", "把", "对", "中", "后", "上", "下", "这", "那", "一个", "一种",
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "from", "into", "is", "are",
}

COMPANY_PATTERNS = {
    "nvidia": r"英伟达|NVIDIA|GTC",
    "anthropic": r"Anthropic",
    "openai": r"OpenAI|GPT",
    "kimi": r"Kimi|月之暗面|杨植麟",
    "xiaomi": r"小米",
    "mistral": r"Mistral",
}

NARRATIVE_PATTERNS = {
    "agent-industry": r"Agent|智能体|SaaS|代工|接管|工具检索",
    "compute": r"英伟达|NVIDIA|GTC|GPU|算力|推理|芯片|数据中心",
    "safety": r"安全|提示注入|prompt injection|红队|越狱",
    "consumer-hardware": r"手机|PC|眼镜|终端|玩家",
}


def tokenize(text: str) -> set[str]:
    text = text.lower()
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9\-\.]{1,}", text)
    return {p for p in parts if p not in STOPWORDS}


def detect_company_flags(title: str) -> set[str]:
    out = set()
    for key, pat in COMPANY_PATTERNS.items():
        if re.search(pat, title, re.I):
            out.add(key)
    return out


def detect_narratives(title: str) -> set[str]:
    out = set()
    for key, pat in NARRATIVE_PATTERNS.items():
        if re.search(pat, title, re.I):
            out.add(key)
    return out


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


def recent_title_penalty(title: str, recent_titles: list[str]) -> tuple[float, dict]:
    toks = tokenize(title)
    companies = detect_company_flags(title)
    narratives = detect_narratives(title)
    penalty = 0.0
    reasons = {
        "overlap": 0.0,
        "company": 0.0,
        "narrative": 0.0,
    }
    for old in recent_titles:
        old_toks = tokenize(old)
        if toks and old_toks:
            overlap = len(toks & old_toks) / max(1, len(toks | old_toks))
            if overlap >= 0.45:
                p = 2.0 * overlap
                penalty += p
                reasons["overlap"] = max(reasons["overlap"], round(p, 3))
        old_companies = detect_company_flags(old)
        old_narratives = detect_narratives(old)
        if companies and old_companies and (companies & old_companies):
            penalty += 1.2
            reasons["company"] = max(reasons["company"], 1.2)
        if narratives and old_narratives and (narratives & old_narratives):
            penalty += 1.0
            reasons["narrative"] = max(reasons["narrative"], 1.0)
    return penalty, reasons


def load_recent_titles(auto_dir: Path, limit: int = 8) -> list[str]:
    titles = []
    if not auto_dir.exists():
        return titles
    for md in sorted(auto_dir.glob("*/article.md"), reverse=True):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"^title:\s*(.+)$", text, re.M)
        if not m:
            continue
        title = m.group(1).strip()
        if not title or title in {"今日科技科普", "标题建议（5个）"}:
            continue
        if len(title) < 8:
            continue
        if title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def score_item(it: dict, recent_titles: list[str]) -> tuple[float, dict]:
    title = it.get("title", "") or ""
    s = score(title)

    # GitHub is auxiliary (AI/LLM trending signal). Apply heavy downweight so it won't dominate media headlines.
    if it.get("kind") == "github":
        s *= 0.35
        stars = int(it.get("stars") or 0)
        # Small popularity nudge (still downweighted overall)
        s += math.log10(max(1, stars)) * 0.3

    novelty_penalty, novelty_detail = recent_title_penalty(title, recent_titles)
    s -= novelty_penalty
    return s, novelty_detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--extra", action="append", default=[], help="extra items json (same schema: {items:[...]})")
    ap.add_argument("--out")
    ap.add_argument("--recent-auto-dir", default="wechat-publisher-out/auto")
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    items = list(data.get("items") or [])

    for extra_path in args.extra:
        try:
            extra = json.loads(Path(extra_path).read_text(encoding="utf-8"))
            items.extend(extra.get("items") or [])
        except Exception:
            pass

    recent_titles = load_recent_titles(Path(args.recent_auto_dir))

    for it in items:
        raw_score, novelty_detail = score_item(it, recent_titles)
        it["score"] = round(float(raw_score), 3)
        if any(v > 0 for v in novelty_detail.values()):
            it["noveltyPenalty"] = novelty_detail

    items_sorted = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    top = items_sorted[0] if items_sorted else None

    brief = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": sorted({(it.get('sourceBlog') or it.get('source') or data.get('blog') or 'unknown') for it in items}),
        "recentTitlesUsedForPenalty": recent_titles,
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
