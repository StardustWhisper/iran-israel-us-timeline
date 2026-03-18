#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

NOTION_VERSION = os.environ.get('NOTION_VERSION', '2022-06-28')
TOKEN = os.environ.get('NOTION_TOKEN')
if not TOKEN:
    raise SystemExit('NOTION_TOKEN missing')


def notion_request(method: str, path: str, payload=None):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request('https://api.notion.com/v1' + path, data=data, method=method)
    req.add_header('Authorization', f'Bearer {TOKEN}')
    req.add_header('Notion-Version', NOTION_VERSION)
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8')
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        raise SystemExit(f'Notion HTTP {e.code}: {body[:500]}')


def get_database(db_id: str):
    code, data = notion_request('GET', f'/databases/{db_id}')
    if code != 200:
        raise SystemExit('Failed to fetch Notion database schema')
    return data


def split_frontmatter(text: str):
    if text.startswith('---\n'):
        parts = text.split('\n---\n', 1)
        if len(parts) == 2:
            fm_raw = parts[0][4:]
            body = parts[1]
            meta = {}
            for line in fm_raw.splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    meta[k.strip()] = v.strip()
            return meta, body
    return {}, text


def rich_text(content: str):
    return [{"type": "text", "text": {"content": content[:2000]}}]


def md_to_blocks(body: str):
    blocks = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith('### '):
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": rich_text(line[4:].strip())}})
            i += 1
            continue
        if line.startswith('## '):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(line[3:].strip())}})
            i += 1
            continue
        if line.startswith('# '):
            blocks.append({"object": "block", "type": "heading_1", "heading_1": {"rich_text": rich_text(line[2:].strip())}})
            i += 1
            continue
        if line.startswith('- '):
            blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(line[2:].strip())}})
            i += 1
            continue
        if re.match(r'^\d+\.\s+', line):
            text = re.sub(r'^\d+\.\s+', '', line)
            blocks.append({"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": rich_text(text)}})
            i += 1
            continue
        if line.startswith('> '):
            blocks.append({"object": "block", "type": "quote", "quote": {"rich_text": rich_text(line[2:].strip())}})
            i += 1
            continue
        para = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#|##|###|> |- |\d+\.\s+)', lines[i]):
            para.append(lines[i].strip())
            i += 1
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(' '.join(para))}})
    return blocks


def append_children(page_id: str, children: list[dict]):
    chunk = []
    for block in children:
        chunk.append(block)
        if len(chunk) >= 80:
            notion_request('PATCH', f'/blocks/{page_id}/children', {'children': chunk})
            chunk = []
    if chunk:
        notion_request('PATCH', f'/blocks/{page_id}/children', {'children': chunk})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--md', required=True)
    ap.add_argument('--database-id', required=True)
    ap.add_argument('--source-url', default='')
    ap.add_argument('--topic', default='')
    ap.add_argument('--wechat-media-id', default='')
    args = ap.parse_args()

    text = Path(args.md).read_text(encoding='utf-8')
    meta, body = split_frontmatter(text)
    title = meta.get('title') or args.topic or Path(args.md).stem
    db = get_database(args.database_id)
    props = db.get('properties') or {}
    title_prop = None
    for k, v in props.items():
        if v.get('type') == 'title':
            title_prop = k
            break
    if not title_prop:
        raise SystemExit('No title property found in target Notion database')

    page_props = {
        title_prop: {'title': [{"type": "text", "text": {"content": title[:200]}}]}
    }
    if '摘要' in props:
        summary = re.sub(r'\s+', ' ', body).strip()[:280]
        page_props['摘要'] = {'rich_text': [{"type": "text", "text": {"content": summary}}]}
    if '类型' in props:
        page_props['类型'] = {'select': {'name': 'info'}}
    if '节点' in props:
        page_props['节点'] = {'select': {'name': 'MOSS'}}
    if '发布状态' in props:
        page_props['发布状态'] = {'select': {'name': '草稿'}}
    if '时间' in props:
        shanghai_now = datetime.now(ZoneInfo('Asia/Shanghai')).replace(microsecond=0)
        page_props['时间'] = {'date': {'start': shanghai_now.isoformat()}}

    page_payload = {
        'parent': {'database_id': args.database_id},
        'properties': page_props,
    }
    code, created = notion_request('POST', '/pages', page_payload)
    if code != 200:
        raise SystemExit('Failed to create Notion page')
    page_id = created['id']

    preface = []
    if args.topic:
        preface.append({"object": "block", "type": "callout", "callout": {"rich_text": rich_text(f"自动出稿选题：{args.topic}"), "icon": {"emoji": "📝"}}})
    if args.source_url:
        preface.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(f"主参考链接：{args.source_url}")}})
    if args.wechat_media_id:
        preface.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(f"微信公众号草稿 Media ID：{args.wechat_media_id}")}})
    if preface:
        preface.append({"object": "block", "type": "divider", "divider": {}})

    blocks = preface + md_to_blocks(body)
    append_children(page_id, blocks)
    print(json.dumps({'page_id': page_id, 'url': created.get('url'), 'title': title}, ensure_ascii=False))


if __name__ == '__main__':
    main()
