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

