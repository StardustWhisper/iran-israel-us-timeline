# OpenRouter 多账号/多 Key 分摊（规划稿）

目标：
- OpenRouter 免费账号每日 50 requests 的硬上限无法突破。
- 通过 **“多 Key 轮询 + 不把 OpenRouter 当主力”**，让日常请求尽量走本地/自建/其他免费 Provider；OpenRouter 仅作为兜底或特定模型调用。

> 注意：本文只描述机制，不包含任何明文 key。所有 key 只放在环境变量/私密配置文件中，不进入 Git、Notion、长期记忆。

---

## 0. 总体策略（推荐默认）

1) 主力不走 OpenRouter：
- primary：`cpa-plus/gpt-5.2`
- fallbacks：`zai-coding-plan/glm-4.7` → `codestral/codestral-latest` → （最后才是）OpenRouter free 模型

2) OpenRouter free 只在两类场景使用：
- 明确指定要用某个 OpenRouter free 模型
- 其它 provider 全不可用时兜底

---

## 1. 多 Key 分摊的两种实现方式

### 方案 A（最稳、最少改动）：多 Provider 别名（openrouter1/openrouter2/...）

思路：在 `openclaw.json` 里复制多个 provider 配置，baseUrl 相同，apiKey 指向不同 env var。

示例：
- providers.openrouter1.apiKey = `${OPENROUTER_API_KEY_1}`
- providers.openrouter2.apiKey = `${OPENROUTER_API_KEY_2}`
- providers.openrouter3.apiKey = `${OPENROUTER_API_KEY_3}`

然后把同一个模型分别挂到多个 provider 上（等价于多入口）：
- openrouter1/qwen/qwen3.6-plus-preview:free
- openrouter2/qwen/qwen3.6-plus-preview:free
- openrouter3/qwen/qwen3.6-plus-preview:free

使用时：
- 手动指定模型入口（最可控）
- 或者在 fallbacks 里按顺序排列 openrouter1 → openrouter2 → openrouter3

优点：
- 实现简单，不需要写代码
- 行为透明（你能明确知道用的是哪个 key）

缺点：
- 配置会变长
- 轮询是“线性失败回退”，不是按配额智能调度

---

### 方案 B（更自动）：OpenRouter Key Router（本地轻量代理）

思路：本机起一个极薄的 HTTP 代理（OpenAI 兼容），接收请求后：
- 按 key 的剩余额度/当天已用次数选择一个 key
- 遇到 429/limit reached 自动切换 key
- 失败重试带退避

OpenClaw 侧只配置一个 provider：
- providers.openrouter-router.baseUrl = `http://127.0.0.1:<port>/v1`
- apiKey 可空或用内部鉴权

优点：
- 对上层透明
- 自动轮询更聪明

缺点：
- 需要维护一个小服务
- 仍然要自己记录/观测 key 的使用情况

---

## 2. Key 存储规范（强制）

- 只存：`~/.openclaw/.env` 或系统环境变量
- 文件权限：`chmod 600 ~/.openclaw/.env`（以及 openclaw.json）
- 绝不写入：Git、Notion、MEMORY.md、长期记忆库

建议环境变量命名：
- `OPENROUTER_API_KEY_1`
- `OPENROUTER_API_KEY_2`
- `OPENROUTER_API_KEY_3`

---

## 3. 观测与回收

- 每日定时：输出每个 key 的 request 使用情况（只本地日志，不推送）
- 达到阈值：把该 key 从候选列表中临时摘除（或降低优先级）

---

## 4. 推荐落地顺序

1) 先用方案 A（多 provider 别名），5 分钟完成
2) 如果你觉得管理成本高，再上方案 B（key router）
