#!/usr/bin/env python3
"""Select top topic from RSS items and produce a brief for HUGO.

Scoring dimensions:
- base topical relevance (AI / compute / agent etc.)
- novelty penalty from recent local + Notion article history
- WeChat publishability bonus/penalty for公众号适发度
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import urllib.request
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

PRIMARY_TRACK_PATTERNS = [
    (r"AI|人工智能|大模型|模型|LLM|Agent|智能体", 0.9, "主赛道：AI/模型/Agent"),
    (r"推理|算力|GPU|工具|API|工作流|路线图|SOTA", 0.7, "主赛道：推理/工具链/工作流"),
]
SECONDARY_TRACK_PENALTIES = [
    (r"出行|低空|eVTOL|汽车|地产|成交模型", 0.4, "次赛道：偏产业泛题"),
]

INVALID_TITLES = {"今日科技科普", "标题建议（5个）"}

# Not publishable as a WeChat tech column main稿: job posts / hiring
JOB_PATTERNS = [
    r"\b(we\s*are\s*hiring|hiring|job|jobs|career|careers|apply\s+now)\b",
    r"招聘|内推|招人|诚聘|求职|找工作|岗位|职位|JD|简历|面试|Offer|薪资|月薪|年薪",
    r"寻.*工程师|找.*工程师|招.*工程师|诚聘.*工程师",
]


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


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def valid_title(title: str) -> bool:
    title = normalize_title(title)
    return bool(title) and title not in INVALID_TITLES and len(title) >= 8


def base_score(title: str) -> float:
    s = 0.0
    for pat, w in AI_KW:
        if re.search(pat, title, re.I):
            s += w
    for pat, w in PENALTY_KW:
        if re.search(pat, title, re.I):
            s -= w
    s -= max(0, (len(title) - 30)) * 0.02
    return s


def recent_title_penalty(title: str, recent_titles: list[str]) -> tuple[float, dict]:
    toks = tokenize(title)
    companies = detect_company_flags(title)
    narratives = detect_narratives(title)
    penalty = 0.0
    reasons = {"overlap": 0.0, "company": 0.0, "narrative": 0.0}
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


def publishability_score(title: str, item: dict) -> tuple[float, dict]:
    s = 0.0
    reasons = {"bonus": [], "penalty": []}
    title_l = title.lower()
    source = (item.get("sourceBlog") or item.get("source") or "").lower()

    # Hard penalty: job posts are not suitable as main稿
    for pat in JOB_PATTERNS:
        if re.search(pat, title, re.I):
            s -= 6.0
            reasons["penalty"].append("疑似招聘/求职信息，不适合作为公众号主稿")
            break

    # 中文友好 / 国内科技媒体：更适合直接做公众号科普
    if re.search(r"[\u4e00-\u9fff]", title):
        s += 0.8
        reasons["bonus"].append("中文标题友好")
    if source == "36kr-tech":
        s += 0.8
        reasons["bonus"].append("36kr科技媒体适配公众号")
    if source == "infoq":
        s += 0.4
        reasons["bonus"].append("InfoQ 技术解读可展开")

    # 有明显机制/争议/趋势感，适合科普展开
    if re.search(r"为什么|如何|误区|路线图|终结|接管|提示注入|安全|算力|GTC|模型|工具", title, re.I):
        s += 0.7
        reasons["bonus"].append("有机制或趋势可展开")

    # 纯英文、海外快讯、社区碎片，对公众号长文不友好
    if source == "hackernews":
        s -= 1.0
        reasons["penalty"].append("Hacker News 更像线索而非成稿源")
    if source == "v2ex-latest":
        s -= 1.2
        reasons["penalty"].append("V2EX 社区碎片不适合主稿")
    if re.fullmatch(r"[A-Za-z0-9\-\s:,.!?()'\"]+", title or ""):
        s -= 0.8
        reasons["penalty"].append("纯英文标题对中文公众号转化较弱")
    if len(title.split()) <= 5 and re.fullmatch(r"[A-Za-z0-9\-\s:,.!?()'\"]+", title or ""):
        s -= 0.5
        reasons["penalty"].append("过短英文快讯可展开空间有限")
    if re.search(r"releases|launches|introducing|announces", title_l):
        s -= 0.4
        reasons["penalty"].append("偏发布快讯")

    return s, reasons


def track_preference_score(title: str) -> tuple[float, dict]:
    s = 0.0
    reasons = {"bonus": [], "penalty": []}
    for pat, w, note in PRIMARY_TRACK_PATTERNS:
        if re.search(pat, title, re.I):
            s += w
            reasons["bonus"].append(note)
    for pat, w, note in SECONDARY_TRACK_PENALTIES:
        if re.search(pat, title, re.I):
            s -= w
            reasons["penalty"].append(note)
    return s, reasons


def load_recent_titles_from_local(auto_dir: Path, limit: int = 8) -> list[str]:
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
        title = normalize_title(m.group(1))
        if not valid_title(title):
            continue
        if title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def load_recent_titles_from_notion(database_id: str, limit: int = 8) -> list[str]:
    token = os.environ.get("NOTION_TOKEN")
    if not token or not database_id:
        return []
    payload = {
        "page_size": limit * 2,
        "filter": {"property": "节点", "select": {"equals": "MOSS"}},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", "2022-06-28")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    titles = []
    for r in data.get("results", []):
        props = r.get("properties", {})
        title = ''.join(x.get('plain_text', '') for x in props.get('名称', {}).get('title', []))
        title = normalize_title(title)
        if not valid_title(title):
            continue
        if title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def load_recent_titles(auto_dir: Path, notion_db_id: str | None, limit: int = 8) -> list[str]:
    titles = []
    for t in load_recent_titles_from_local(auto_dir, limit=limit):
        if t not in titles:
            titles.append(t)
    for t in load_recent_titles_from_notion(notion_db_id or "", limit=limit):
        if t not in titles:
            titles.append(t)
        if len(titles) >= limit:
            break
    return titles[:limit]


def score_item(it: dict, recent_titles: list[str]) -> tuple[float, dict]:
    title = it.get("title", "") or ""
    s = base_score(title)
    detail = {"noveltyPenalty": None, "publishability": None, "trackPreference": None}

    if it.get("kind") == "github":
        s *= 0.35
        stars = int(it.get("stars") or 0)
        s += math.log10(max(1, stars)) * 0.3

    novelty_penalty, novelty_detail = recent_title_penalty(title, recent_titles)
    s -= novelty_penalty
    if any(v > 0 for v in novelty_detail.values()):
        detail["noveltyPenalty"] = novelty_detail

    pub_score, pub_detail = publishability_score(title, it)
    s += pub_score
    if pub_detail["bonus"] or pub_detail["penalty"]:
        detail["publishability"] = pub_detail

    track_score, track_detail = track_preference_score(title)
    s += track_score
    if track_detail["bonus"] or track_detail["penalty"]:
        detail["trackPreference"] = track_detail

    return s, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--extra", action="append", default=[], help="extra items json (same schema: {items:[...]})")
    ap.add_argument("--out")
    ap.add_argument("--recent-auto-dir", default="wechat-publisher-out/auto")
    ap.add_argument("--notion-db-id", default=os.environ.get("NOTION_ARTICLE_DATABASE_ID", "3188bd97-88dd-8034-ae05-d4c7f2b4b10e"))
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    items = list(data.get("items") or [])
    for extra_path in args.extra:
        try:
            extra = json.loads(Path(extra_path).read_text(encoding="utf-8"))
            items.extend(extra.get("items") or [])
        except Exception:
            pass

    recent_titles = load_recent_titles(Path(args.recent_auto_dir), args.notion_db_id)

    for it in items:
        raw_score, detail = score_item(it, recent_titles)
        it["score"] = round(float(raw_score), 3)
        if detail.get("noveltyPenalty"):
            it["noveltyPenalty"] = detail["noveltyPenalty"]
        if detail.get("publishability"):
            it["publishability"] = detail["publishability"]
        if detail.get("trackPreference"):
            it["trackPreference"] = detail["trackPreference"]

    prelim = sorted(items, key=lambda x: x.get("score", 0), reverse=True)

    # Source diversity pass: avoid one source monopolizing the whole top list.
    source_seen = {}
    for it in prelim:
        source = (it.get('sourceBlog') or it.get('source') or 'unknown')
        seen = source_seen.get(source, 0)
        source_penalty = 0.0
        if seen >= 1:
            source_penalty = min(0.9, seen * 0.35)
            it['score'] = round(float(it.get('score', 0)) - source_penalty, 3)
            it['sourceDiversityPenalty'] = round(source_penalty, 3)
        source_seen[source] = seen + 1

    items_sorted = sorted(prelim, key=lambda x: x.get("score", 0), reverse=True)
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
