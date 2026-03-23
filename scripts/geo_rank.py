#!/usr/bin/env python3
"""Rank geo/econ items from merged RSS list.

Heuristic scoring; no external deps.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

# Keyword weights
CORE_KW = [
    (r"战争|冲突|军事|袭击|停火|导弹|无人机|核|武装|政变|边境", 4.0),
    (r"制裁|关税|贸易|出口管制|禁令|限制|反制|WTO", 3.5),
    (r"油价|原油|天然气|能源|OPEC|电力|电网|LNG", 3.0),
    (r"通胀|CPI|PPI|利率|加息|降息|汇率|货币政策|央行", 3.0),
    (r"国债|债券|财政|预算|赤字|税收|债务上限", 2.5),
    (r"供应链|航运|港口|物流|运费|红海|巴拿马运河|苏伊士", 2.5),
    (r"关停|减产|罢工|停工|裁员|破产|重组|并购", 2.0),
    (r"粮食|小麦|玉米|大豆|化肥|稀土|关键矿产|锂|钴|镍", 2.0),
    (r"地缘政治|大国博弈|盟友|北约|印太|中东|欧洲|亚太", 2.0),
]
EN_KW = [
    (r"war|conflict|missile|nuclear|ceasefire|drone", 3.5),
    (r"sanction|tariff|export control|ban", 3.0),
    (r"oil|crude|gas|energy|opec|lng", 2.5),
    (r"inflation|cpi|ppi|interest rate|central bank|fx", 2.5),
    (r"debt|bond|fiscal|budget|deficit", 2.0),
    (r"supply chain|shipping|port|freight|red sea|suez|panama", 2.0),
    (r"strike|shutdown|bankrupt|merger|acquisition", 1.5),
    (r"grain|wheat|corn|soy|fertilizer|rare earth|lithium|cobalt|nickel", 1.5),
]
PENALTY = [
    (r"娱乐|明星|体育|足球|电影|综艺", 2.0),
    (r"测评|优惠|折扣|促销|发布会直播", 1.5),
]

STOPWORDS = {
    "the","a","an","and","or","for","to","of","in","on","with","from","into","is","are",
    "的","了","和","与","及","或","在","是","把","对","中","后","上","下","这","那","一个","一种",
}


def normalize_title(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def base_score(title: str) -> float:
    s = 0.0
    for pat, w in CORE_KW:
        if re.search(pat, title, re.I):
            s += w
    for pat, w in EN_KW:
        if re.search(pat, title, re.I):
            s += w
    for pat, w in PENALTY:
        if re.search(pat, title, re.I):
            s -= w
    if len(title) > 60:
        s -= (len(title) - 60) * 0.01
    return s


def tokenize(text: str) -> set[str]:
    text = (text or "").lower()
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9\-\.]{1,}", text)
    return {p for p in parts if p not in STOPWORDS}


def dedup(items: list[dict]) -> list[dict]:
    seen_urls = set()
    out = []
    for it in items:
        url = (it.get("url") or "").strip()
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(it)
    # Title-based fuzzy dedup
    deduped = []
    seen_titles = []
    for it in out:
        title = normalize_title(it.get("title") or "")
        toks = tokenize(title)
        is_dup = False
        for old_title, old_toks in seen_titles:
            if not toks or not old_toks:
                continue
            overlap = len(toks & old_toks) / max(1, len(toks | old_toks))
            if overlap >= 0.6:
                is_dup = True
                break
        if not is_dup:
            deduped.append(it)
            seen_titles.append((title, toks))
    return deduped


def rank_items(items: list[dict]) -> list[dict]:
    for it in items:
        title = normalize_title(it.get("title") or "")
        s = base_score(title)
        it["score"] = round(float(s), 3)
    return sorted(items, key=lambda x: x.get("score", 0), reverse=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    items = list(data.get("items") or [])
    items = [it for it in items if it.get("title") and it.get("url")]
    items = dedup(items)
    ranked = rank_items(items)

    top = ranked[: max(1, args.top)]
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(ranked),
        "top": top[0] if top else None,
        "topN": top,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
