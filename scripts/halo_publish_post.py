#!/usr/bin/env python3
"""Publish a Markdown article to Halo 2 via RESTful API.

Design goals:
- No secrets in repo: token comes from env.
- Best-effort: create+publish a new post from a markdown file.
- Minimal dependencies (requests only).
- Do NOT break upstream pipelines: default behavior is non-strict (exit 0 + JSON output even on failure).

Env:
- HALO_BASE_URL: e.g. https://www.lambda.xin
- HALO_TOKEN: personal access token (PAT)
Optional:
- HALO_OWNER: default 'lambda'
- HALO_CATEGORY_ID: category resource id/name (e.g. category-xxxx or uuid)
- HALO_CATEGORY_NAME: if ID not provided, find/create by displayName (e.g. 公众号)
- HALO_TAG_IDS: comma-separated tag resource names (e.g. tag-xxxx,uuid)

Usage:
  halo_publish_post.py --md path/to/article_raw.md [--title ...] [--slug ...] [--category "公众号"] [--tag tech]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

import requests

API_PREFIX = "/apis/content.halo.run/v1alpha1"


def env_required(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"Missing env {name}")
    return v


def slugify(text: str, max_len: int = 60) -> str:
    # Keep ascii letters/digits, convert spaces to '-', drop other chars.
    t = text.strip().lower()
    t = re.sub(r"\s+", "-", t)
    t = re.sub(r"[^a-z0-9\-]", "", t)
    t = re.sub(r"-+", "-", t).strip("-")
    if not t:
        t = "auto-" + dt.datetime.now().strftime("%Y%m%d")
    return t[:max_len]


def first_title_from_md(md: str) -> str:
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("# "):
            return s[2:].strip()
    # fallback: first non-empty line
    for ln in md.splitlines():
        if ln.strip():
            return ln.strip()[:80]
    return "Untitled"


def halo_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    resp = session.request(method, url, timeout=30, **kwargs)
    if resp.status_code >= 400:
        # Show a short error but don't leak token.
        body = resp.text
        if len(body) > 2000:
            body = body[:2000] + "..."
        raise RuntimeError(f"Halo API {method} {url} failed: {resp.status_code} {body}")
    return resp


def get_or_create_tag(session: requests.Session, base: str, slug: str, display_name: Optional[str] = None) -> str:
    """Return tag resource name (metadata.name)."""
    url = base + API_PREFIX + "/tags?size=200"
    items = halo_request(session, "GET", url).json().get("items") or []
    for it in items:
        if (it.get("spec") or {}).get("slug") == slug:
            return (it.get("metadata") or {}).get("name")

    payload = {
        "apiVersion": "content.halo.run/v1alpha1",
        "kind": "Tag",
        "metadata": {"generateName": "tag-"},
        "spec": {
            "displayName": display_name or slug,
            "slug": slug,
            "color": "#ffffff",
            "cover": "",
        },
    }
    resp = halo_request(session, "POST", base + API_PREFIX + "/tags", json=payload).json()
    return (resp.get("metadata") or {}).get("name")


def get_or_create_category(session: requests.Session, base: str, name: str, slug: Optional[str] = None) -> str:
    """Return category resource name (metadata.name)."""
    url = base + API_PREFIX + "/categories?size=200"
    items = halo_request(session, "GET", url).json().get("items") or []
    for it in items:
        spec = it.get("spec") or {}
        if spec.get("displayName") == name:
            return (it.get("metadata") or {}).get("name")

    if not slug:
        # ascii-only slug for category
        slug = slugify(name, max_len=40)

    payload = {
        "apiVersion": "content.halo.run/v1alpha1",
        "kind": "Category",
        "metadata": {"generateName": "category-"},
        "spec": {
            "displayName": name,
            "slug": slug,
            "description": "",
            "cover": "",
            "template": "",
            "priority": 0,
            "children": [],
            "preventParentPostCascadeQuery": False,
            "hideFromList": False,
        },
    }
    resp = halo_request(session, "POST", base + API_PREFIX + "/categories", json=payload).json()
    return (resp.get("metadata") or {}).get("name")


def create_post(session: requests.Session, base: str, title: str, slug: str, owner: str,
                category_ids: List[str], tag_ids: List[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "apiVersion": "content.halo.run/v1alpha1",
        "kind": "Post",
        "metadata": {
            "generateName": "post-",
            "annotations": {
                "content.halo.run/preferred-editor": "bytemd",
            },
        },
        "spec": {
            "title": title,
            "slug": slug,
            "owner": owner,
            "template": "",
            "cover": "",
            "deleted": False,
            "publish": False,
            "pinned": False,
            "allowComment": False,
            "visible": "PUBLIC",
            "priority": 0,
            "excerpt": {"autoGenerate": True, "raw": ""},
            "categories": category_ids,
            "tags": tag_ids,
            "htmlMetas": [],
        },
    }
    return halo_request(session, "POST", base + API_PREFIX + "/posts", json=payload).json()


def create_snapshot(session: requests.Session, base: str, post_name: str, markdown: str, owner: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "apiVersion": "content.halo.run/v1alpha1",
        "kind": "Snapshot",
        "metadata": {"generateName": "snapshot-"},
        "spec": {
            "subjectRef": {
                "group": "content.halo.run",
                "version": "v1alpha1",
                "kind": "Post",
                "name": post_name,
            },
            "rawType": "markdown",
            "rawPatch": markdown,
            "contentPatch": "[]",
            "owner": owner,
            "contributors": [owner],
        },
    }
    return halo_request(session, "POST", base + API_PREFIX + "/snapshots", json=payload).json()


def json_patch(session: requests.Session, base: str, resource_path: str, ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    url = base + API_PREFIX + resource_path
    resp = session.patch(
        url,
        data=json.dumps(ops).encode("utf-8"),
        headers={"Content-Type": "application/json-patch+json"},
        timeout=30,
    )
    if resp.status_code >= 400:
        body = resp.text
        if len(body) > 2000:
            body = body[:2000] + "..."
        raise RuntimeError(f"Halo API PATCH {url} failed: {resp.status_code} {body}")
    return resp.json()


def publish_post(session: requests.Session, base: str, post_name: str, publish_time: Optional[str] = None) -> Dict[str, Any]:
    """Attempt to publish. Some installs require privileged endpoints; we fallback to spec.publish=true."""
    # 1) privileged publish endpoints (often forbidden for low-scope PATs)
    for ep in (f"/posts/{post_name}/publish", f"/posts/{post_name}/publishings", f"/posts/{post_name}/publishing", f"/posts/{post_name}/release"):
        url = base + API_PREFIX + ep
        try:
            return halo_request(session, "POST", url).json()
        except Exception:
            pass

    # 2) best-effort: set spec.publish=true (and optionally publishTime)
    ops: List[Dict[str, Any]] = [
        {"op": "replace", "path": "/spec/publish", "value": True},
    ]
    if publish_time:
        ops.append({"op": "add", "path": "/spec/publishTime", "value": publish_time})
    return json_patch(session, base, f"/posts/{post_name}", ops)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True, help="Path to markdown (article_raw.md)")
    ap.add_argument("--title", default="", help="Override title")
    ap.add_argument("--slug", default="", help="Override slug")
    ap.add_argument("--source-url", default="", help="Original source url for reference (optional)")
    ap.add_argument("--category", default="", help="Category displayName (find or create), e.g. 公众号")
    ap.add_argument("--tag", action="append", default=[], help="Tag slug(s) to ensure and attach, e.g. --tag tech")
    ap.add_argument("--publish", action="store_true", help="Attempt to publish (may be forbidden for PATs)")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero on failure")
    args = ap.parse_args()

    base = env_required("HALO_BASE_URL").rstrip("/")
    token = env_required("HALO_TOKEN")
    owner = os.environ.get("HALO_OWNER", "lambda")

    md_path = args.md
    markdown = open(md_path, "r", encoding="utf-8").read().strip() + "\n"

    title = args.title.strip() or first_title_from_md(markdown)
    slug = args.slug.strip() or slugify(title)

    # prepare session
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    # categories
    category_ids: List[str] = []
    category_id = os.environ.get("HALO_CATEGORY_ID", "").strip()
    if category_id:
        category_ids = [category_id]
    else:
        category_name = (args.category or os.environ.get("HALO_CATEGORY_NAME", "")).strip()
        if category_name:
            category_ids = [get_or_create_category(session, base, category_name)]

    # tags
    tag_ids: List[str] = []
    env_tag_ids = [t.strip() for t in (os.environ.get("HALO_TAG_IDS", "") or "").split(",") if t.strip()]
    tag_ids.extend(env_tag_ids)

    # Always include at least one tag for discoverability.
    tag_slugs = args.tag or ["tech"]
    for ts in tag_slugs:
        tag_ids.append(get_or_create_tag(session, base, ts, display_name=ts))

    # 1) create post (draft)
    post = create_post(session, base, title=title, slug=slug, owner=owner, category_ids=category_ids, tag_ids=tag_ids)
    post_name = (post.get("metadata") or {}).get("name")
    if not post_name:
        raise RuntimeError(f"Unexpected post response missing metadata.name: keys={list(post.keys())}")

    # 2) create snapshot containing full markdown, and wire it as head/base/release
    snap = create_snapshot(session, base, post_name, markdown, owner=owner)
    snap_name = (snap.get("metadata") or {}).get("name")
    if not snap_name:
        raise RuntimeError("Snapshot creation returned no metadata.name")

    # JSON-patch the post to reference this snapshot
    ops = [
        {"op": "add", "path": "/spec/headSnapshot", "value": snap_name},
        {"op": "add", "path": "/spec/baseSnapshot", "value": snap_name},
        {"op": "add", "path": "/spec/releaseSnapshot", "value": snap_name},
    ]
    post2 = json_patch(session, base, f"/posts/{post_name}", ops)

    # 3) attempt publish (optional). With PATs this is often forbidden; keep post in DRAFT.
    published: Dict[str, Any] = {}
    if args.publish:
        now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        published = publish_post(session, base, post_name, publish_time=now)

    # output summary JSON
    out = {
        "ok": True,
        "title": title,
        "slug": slug,
        "post_name": post_name,
        "snapshot": snap_name,
        "permalink": ((published.get("status") or {}).get("permalink")) or ((post2.get("status") or {}).get("permalink")) or ((post.get("status") or {}).get("permalink")),
        "phase": (published.get("status") or {}).get("phase") or (post2.get("status") or {}).get("phase") or (post.get("status") or {}).get("phase"),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        # non-strict by default: print JSON and exit 0 unless --strict
        strict = "--strict" in sys.argv
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        raise SystemExit(1 if strict else 0)
