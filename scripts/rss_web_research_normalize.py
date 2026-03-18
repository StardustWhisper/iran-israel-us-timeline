#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

TYPE_WEIGHT = {
    'official': 4,
    'research': 3,
    'media': 2,
    'analysis': 1,
}

DOMAIN_HINTS = [
    ('official', [
        'openai.com', 'anthropic.com', 'googleblog.com', 'blog.google', 'aws.amazon.com',
        'microsoft.com', 'github.blog', 'nvidia.com', 'cloudflare.com', 'meta.com'
    ]),
    ('research', [
        'arxiv.org', 'research.google', 'microsoft.com/en-us/research', 'deepmind.google', 'huggingface.co/papers'
    ]),
    ('media', [
        'theverge.com', 'techcrunch.com', 'wired.com', '36kr.com', 'infoq.com', 'cnbc.com', 'bloomberg.com'
    ]),
]


def guess_type(url: str, old: str | None = None) -> str:
    if old in TYPE_WEIGHT:
        return old
    host = (urlparse(url).netloc or '').lower()
    for kind, domains in DOMAIN_HINTS:
        for d in domains:
            if d in host:
                return kind
    return 'analysis'


def norm_url(url: str) -> str:
    u = (url or '').strip()
    return re.sub(r'#.*$', '', u)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', default='')
    ap.add_argument('--source-url', default='')
    args = ap.parse_args()

    p = Path(args.inp)
    content = p.read_text(encoding='utf-8') if p.exists() else ''
    start = content.find('{')
    end = content.rfind('}')
    if start == -1 or end == -1 or end < start:
        data = {'summary': [], 'sources': [], 'angles': []}
    else:
        try:
            data = json.loads(content[start:end+1])
        except Exception:
            data = {'summary': [], 'sources': [], 'angles': []}

    seen = set()
    cleaned_sources = []
    for src in data.get('sources') or []:
        url = norm_url(src.get('url') or '')
        title = (src.get('title') or '').strip()
        if not url or not title or url == args.source_url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        kind = guess_type(url, (src.get('type') or '').strip())
        cleaned_sources.append({
            'title': title,
            'url': url,
            'type': kind,
            'note': (src.get('note') or '').strip(),
        })

    cleaned_sources.sort(key=lambda x: (-TYPE_WEIGHT.get(x['type'], 0), x['title']))
    cleaned_sources = cleaned_sources[:5]

    summary = []
    seen_sum = set()
    for item in data.get('summary') or []:
        s = re.sub(r'\s+', ' ', str(item)).strip(' -\n\t')
        if len(s) < 8:
            continue
        k = s.lower()
        if k in seen_sum:
            continue
        seen_sum.add(k)
        summary.append(s)
    summary = summary[:5]

    angles = []
    seen_ang = set()
    for item in data.get('angles') or []:
        s = re.sub(r'\s+', ' ', str(item)).strip(' -\n\t')
        if len(s) < 4:
            continue
        k = s.lower()
        if k in seen_ang:
            continue
        seen_ang.add(k)
        angles.append(s)
    angles = angles[:4]

    quality_ok = len(cleaned_sources) >= 2 or len(summary) >= 2
    out = {
        'topic': args.title,
        'qualityOk': quality_ok,
        'summary': summary,
        'sources': cleaned_sources,
        'angles': angles,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
