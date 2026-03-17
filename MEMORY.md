# MEMORY.md — Long-Term Memory (Curated)

Created: 2026-03-03

This file is intentionally curated (not raw logs). Add only stable, high-signal facts and preferences.

## People
- 

## Preferences
- 沟通偏好：中文优先；务实、直给、少废话（需要展开时再展开）。

## Ongoing projects
- Notion Shared 自动协作：cron `shared-bbs-check` 每分钟运行 `scripts/shared_bbs_bot.py`（Notion API only），按规则在 Shared/MOSS 写入自动回复。

## Environment notes
- 记忆系统：主存储为 LanceDB（`~/.openclaw/memory/lancedb-pro/memories.lance`）。
- Shared BBS bot 规则要点：@MOSS 必回；不明白先问清楚；每次发言必须 @ 相关节点并署名 `MOSS (a11)`；避免循环（自己的回复不能包含 `@MOSS`）；仅 stdout==`WROTE` 才触发通知；只允许写 Shared/MOSS（ROCK/Spark 只读）。
- 2026-03-04 做过会话稳定性修复：session store 从 1142 清理到 500；gateway 重启后 Telegram 通道可用；旧 `telegram:slash:5966032490` 仅剩索引备份，无原 transcript，无法无损切回。
- grok2api 自动注册排障要点（Cloudflare 临时邮箱 Worker）：mail.aiuv.top 为前端、真实 API base 为 api.aiuv.top；Worker needAuth 后普遍要求 `x-custom-auth`，部分接口还需 `Authorization: Bearer <jwt>`（双鉴权）；因此 grok2api 需适配 `/api/new_address` 并在拉邮件时同时带 `x-custom-auth` + `Authorization`；结论只记录机制，不记录任何明文凭证。

## Operation Rules (Hard Lessons)
- **⚠️ 任何密钥/令牌/可登录凭证（API key、Access Key、OAuth client_secret、JWT、Cookie 等）不写入“长期记忆”**。如不小心进入记忆，优先删除/脱敏后再用“机制 + 位置/路径 + 如何重新获取”的方式重记。
- **⚠️ CLIProxyAPIPlus 升级原则**：此项目承载所有 GPT 模型 API。在对其进行修复/升级等可能中断服务的操作前，必须先把我当前会话的模型切到非 GPT 模型（如 GLM），避免“修到一半 API 断了任务也断”。
