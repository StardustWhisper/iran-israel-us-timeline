#!/usr/bin/env python3
"""Delete a WeChat Official Account draft by media_id.

Uses Official Account API:
- GET  https://api.weixin.qq.com/cgi-bin/token
- POST https://api.weixin.qq.com/cgi-bin/draft/delete

Credentials are read from env:
  WECHAT_APP_ID, WECHAT_APP_SECRET

Usage:
  python3 scripts/wechat_draft_delete.py --media-id <MEDIA_ID>

Notes:
- Prints a short JSON result to stdout.
- Does NOT print access_token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request


def http_get_json(url: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    return json.loads(data)


def http_post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    return json.loads(data)


def get_access_token(appid: str, secret: str) -> str:
    qs = urllib.parse.urlencode(
        {
            "grant_type": "client_credential",
            "appid": appid,
            "secret": secret,
        }
    )
    url = f"https://api.weixin.qq.com/cgi-bin/token?{qs}"
    j = http_get_json(url)
    token = j.get("access_token")
    if not token:
        raise RuntimeError(f"failed to get access_token: {j}")
    return token


def delete_draft(token: str, media_id: str) -> dict:
    url = f"https://api.weixin.qq.com/cgi-bin/draft/delete?access_token={urllib.parse.quote(token)}"
    return http_post_json(url, {"media_id": media_id})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--media-id", required=True)
    args = ap.parse_args()

    appid = os.environ.get("WECHAT_APP_ID", "").strip()
    secret = os.environ.get("WECHAT_APP_SECRET", "").strip()

    if not appid or not secret:
        print(json.dumps({"ok": False, "error": "missing WECHAT_APP_ID/WECHAT_APP_SECRET"}, ensure_ascii=False))
        return 2

    try:
        token = get_access_token(appid, secret)
        res = delete_draft(token, args.media_id)
        ok = (res.get("errcode") == 0)
        print(json.dumps({"ok": ok, "media_id": args.media_id, "result": res}, ensure_ascii=False))
        return 0 if ok else 3
    except Exception as e:
        print(json.dumps({"ok": False, "media_id": args.media_id, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
