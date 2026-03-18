#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

STOPWORDS = {
    '的','了','和','与','及','或','在','是','把','对','中','后','上','下','这','那','一个','一种','我们','你','我',
    'the','a','an','and','or','for','to','of','in','on','with','from','into','how','what','why','is','are','be','by',
    'will','can','does','doesn','about'
}

SYNONYMS = {
    'agent': ['agent', 'agents', '智能体'],
    '智能体': ['agent', 'agents', '智能体'],
    'saaas': ['saas'],
    'saas': ['saas', '软件'],
    'ai': ['ai', '人工智能', '大模型', '模型', 'llm'],
    '大模型': ['ai', '人工智能', '大模型', '模型', 'llm'],
    '推理': ['推理', 'inference'],
    '算力': ['算力', 'gpu', '芯片', 'nvidia', '英伟达', '数据中心'],
    '安全': ['安全', 'prompt injection', '提示注入', '越狱'],
    '提示词注入': ['prompt injection', '提示注入'],
    '提示注入': ['prompt injection', '提示注入'],
    '英伟达': ['nvidia', '英伟达', 'gtc'],
    '黄仁勋': ['黄仁勋', 'nvidia', '英伟达', 'gtc'],
    'gtc': ['gtc', 'nvidia', '英伟达'],
}


def tokenize(text: str) -> list[str]:
    text = text.lower()
    parts = re.findall(r'[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9\-\.]{1,}', text)
    out = []
    for p in parts:
        if p in STOPWORDS:
            continue
        out.append(p)
    return out


def expand_keywords(title: str, limit: int = 8) -> list[str]:
    toks = tokenize(title)
    counts = Counter(toks)
    picked = [k for k, _ in counts.most_common(limit)]
    expanded = []
    seen = set()
    for kw in picked:
        for item in SYNONYMS.get(kw, [kw]):
            if item not in seen:
                expanded.append(item)
                seen.add(item)
    return expanded[:12]


def score_item(title: str, keywords: list[str], source_url: str) -> int:
    title_l = title.lower()
    score = 0
    for kw in keywords:
        if kw.lower() in title_l:
            score += 2
    if source_url and source_url in title:
        score -= 10
    return score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--title', required=True)
    ap.add_argument('--source-url', default='')
    ap.add_argument('--corpus', default='rss/all-new.json')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    corpus_path = Path(args.corpus)
    data = json.loads(corpus_path.read_text(encoding='utf-8'))
    items = data.get('items') or []
    keywords = expand_keywords(args.title)

    related = []
    for it in items:
        t = (it.get('title') or '').strip()
        u = (it.get('url') or '').strip()
        if not t or not u:
            continue
        if u == args.source_url:
            continue
        s = score_item(t, keywords, args.source_url)
        if s > 0:
            related.append({
                'title': t,
                'url': u,
                'source': it.get('sourceBlog') or it.get('source') or 'unknown',
                'published': it.get('published'),
                'score': s,
            })

    related.sort(key=lambda x: (-x['score'], x['source'], x['title']))
    top_related = related[:8]

    out = {
        'topic': args.title,
        'keywords': keywords,
        'related': top_related,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
