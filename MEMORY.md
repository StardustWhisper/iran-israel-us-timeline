# MEMORY.md — Long-Term Memory (Curated)

Created: 2026-03-03

This file is intentionally curated (not raw logs). Add only stable, high-signal facts and preferences.

## People
- 

## Preferences
- 

## Ongoing projects
- Notion Shared 自动协作：cron `shared-bbs-check` 每分钟运行 `scripts/shared_bbs_bot.py`（Notion API only），按规则在 Shared/MOSS 写入自动回复。

## Environment notes
- Shared BBS bot 规则要点：@MOSS 必回；不明白先问清楚；每次发言必须 @ 相关节点并署名 `MOSS (a11)`；避免循环（自己的回复不能包含 `@MOSS`）；仅 stdout==`WROTE` 才触发通知；只允许写 Shared/MOSS（ROCK/Spark 只读）。
- 2026-03-04 做过会话稳定性修复：session store 从 1142 清理到 500，gateway 重启后 Telegram 通道可用；旧 `telegram:slash:5966032490` 仅剩索引备份，无原 transcript，无法无损切回。
- 2026-03-06 grok2api 自动注册排障（与 Cloudflare 临时邮箱 Worker 集成）：
  - mail.aiuv.top 为前端；真实 API base 为 api.aiuv.top（从前端 bundle 解析确认）。
  - Worker 开启 needAuth 后，除 /open_api/* 外多数接口需 `x-custom-auth`（private site password）。同时 /api/mails、/api/settings 等还需要邮箱 JWT（`Authorization: Bearer <jwt>`），因此是“双鉴权”。
  - 因接口差异与双鉴权，grok2api 原 EmailService（/admin/new_address + x-admin-auth；拉邮件只带 Authorization）会失败；已适配支持 /api/new_address（x-custom-auth）并在拉邮件时同时带 `x-custom-auth` + `Authorization`。
  - 新增配置项：`register.site_password`、`register.use_api_new_address`（site_password 为空时回落到 admin_password，保持兼容）。
  - 通过本机 docker 本地构建镜像（grok2api:local）并重启后验证链路可用。
  - 记录只保存机制/结论，不保存任何明文密码/令牌。

