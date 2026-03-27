# 美国-以色列-伊朗冲突时间轴（自 2026-02-28 起）

生成的静态站点：`index.html`（单文件，无依赖）。

## 本地预览

```bash
cd reports/iran-israel-us-timeline
python3 -m http.server 5173
```

然后打开：
- http://127.0.0.1:5173/

## 发布（任选一种）

### 1) Nginx 静态目录
把整个目录拷到你的 Web root：

```bash
sudo mkdir -p /var/www/iran-timeline
sudo cp -r reports/iran-israel-us-timeline/* /var/www/iran-timeline/
```

### 2) GitHub Pages / Cloudflare Pages
直接把 `index.html` 推到仓库或 Pages 项目。

## 数据说明

当前版本先搭了“骨架”（重大节点 + 权威来源链接）。
下一步可以把 2/28 之后逐日补齐：
- 军事行动（空袭/导弹/无人机/重要人物）
- 外交（联合国、停火提案、谈判进展）
- 经济（油价、霍尔木兹航运、制裁、释油）
- 人道（伤亡、难民、基础设施）

你如果希望“完整时间轴”，建议给我一个粒度标准：
- A：每天 0~3 条（只收敛到最关键）
- B：每天 3~10 条（覆盖更全面）
- C：事件驱动（有大事就记，不按天均匀）
