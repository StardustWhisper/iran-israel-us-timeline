#!/usr/bin/env python3
"""Approximate GitHub Trending for AI/LLM repos using GitHub Search API via `gh api`.

Why: GitHub Trending has no official RSS; RSSHub route may be unavailable.
This script produces a daily shortlist of repos that look 'hot' for AI/LLM.

Outputs JSON:
  {"generatedAt":"...Z","items":[{"kind":"github","title":"...","url":"...","stars":1234,"language":"Python","pushedAt":"..."}]}

Notes:
- Requires `gh auth login` already configured.
- Does NOT print any tokens.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


def gh_api(path: str, params: dict[str, str]) -> dict:
    # Use explicit / prefix + GET since gh api defaults to POST when fields are present.
    cmd = ["gh", "api", "-X", "GET", f"/{path.lstrip('/')}" ]
    for k, v in params.items():
        cmd += ["-f", f"{k}={v}"]
    out = subprocess.check_output(cmd, text=True)
    return json.loads(out)


def build_query(days: int, min_stars: int) -> str:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

    # GitHub search has a limit on boolean operators and can be noisy.
    # Pragmatic: use keywords in readme/description; keep OR list within limits.
    # We'll filter out obvious non-AI repos later by requiring an AI keyword hit.
    return (
        f"(llm OR rag OR \"ai agent\" OR langchain OR llama) "
        f"in:description in:readme pushed:>={since} stars:>={min_stars} fork:false archived:false"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--min-stars", type=int, default=200)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out")
    args = ap.parse_args()

    q = build_query(args.days, args.min_stars)
    data = gh_api(
        "search/repositories",
        {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": str(min(100, max(1, args.limit))),
        },
    )

    items = []
    AI_FILTER = re.compile(r"\b(llm|rag|agent|agents|langchain|llama|transformer|diffusion|embedding|vector)\b", re.I)

    for repo in (data.get("items") or [])[: max(100, args.limit)]:
        full_name = repo.get("full_name")
        desc = (repo.get("description") or "").strip()
        readme_hint = ""
        # basic filter: require AI keyword in name/desc/topics
        topics = repo.get("topics") or []
        blob = " ".join([full_name or "", desc, " ".join(topics)])
        if not AI_FILTER.search(blob):
            continue

        stars = int(repo.get("stargazers_count") or 0)
        pushed = repo.get("pushed_at")
        lang = repo.get("language")
        url = repo.get("html_url")
        title = f"GitHub 热门项目：{full_name} — {desc}" if desc else f"GitHub 热门项目：{full_name}"
        items.append(
            {
                "kind": "github",
                "source": "github-search",
                "title": title,
                "repo": full_name,
                "url": url,
                "stars": stars,
                "language": lang,
                "pushedAt": pushed,
            }
        )
        if len(items) >= args.limit:
            break

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "query": q,
        "items": items,
    }

    out = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out + "\n", encoding="utf-8")
    else:
        print(out)


if __name__ == "__main__":
    main()
