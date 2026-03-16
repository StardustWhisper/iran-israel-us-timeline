# CPA / CPA-plus 升级 Runbook（A11）

> 约定：用户说“升级 CPA / 升级 CPA plus”，默认执行本 runbook。

## 目标
升级运行中的 **CLIProxyAPIPlus** 服务（Docker 容器），方式为：
- 拉取 `eceasy/cli-proxy-api-plus:latest` 最新镜像
- 仅重建 `cli-proxy-api-plus` 容器（不影响同 compose 下其他服务）
- 确认容器 `healthy`
- 记录升级前后镜像 digest（便于回滚）

## 环境/路径
- Compose 工程目录：`/home/ubuntu/github/deploy-cli-proxy`
- 容器名：`cli-proxy-api-plus`
- 镜像：`eceasy/cli-proxy-api-plus:latest`
- 端口：`8317`、`8085`

## 配置挂载（重要）
容器使用宿主机挂载配置：
- `deploy-cli-proxy/config.yaml` → `/CLIProxyAPI/config.yaml`
- `deploy-cli-proxy/auths/` → `/CLIProxyAPI/auths/`
- `deploy-cli-proxy/logs/` → `/CLIProxyAPI/logs/`

因此：升级镜像 **不会覆盖** 你的配置文件；配置仍以宿主机为准。

## 标准升级流程（最小风险）
> 注意：重建容器会造成短暂闪断（通常几十秒内）。

### 1) 记录升级前状态（用于回滚）
```bash
cd /home/ubuntu/github/deploy-cli-proxy
sudo docker compose ps
sudo docker inspect cli-proxy-api-plus --format 'Image={{.Image}}  Status={{.State.Status}}  Health={{if .State.Health}}{{.State.Health.Status}}{{end}}'
```

### 2) 拉取最新镜像
```bash
cd /home/ubuntu/github/deploy-cli-proxy
sudo docker compose pull cli-proxy-api-plus
```

### 3) 仅重建该服务（不重启依赖、不动其他容器）
```bash
cd /home/ubuntu/github/deploy-cli-proxy
sudo docker compose up -d --no-deps --force-recreate cli-proxy-api-plus
```

### 4) 升级后检查
```bash
cd /home/ubuntu/github/deploy-cli-proxy
sudo docker compose ps
sudo docker inspect cli-proxy-api-plus --format 'Image={{.Image}}  Status={{.State.Status}}  Health={{if .State.Health}}{{.State.Health.Status}}{{end}}  StartedAt={{.State.StartedAt}}'
sudo docker logs --tail 50 cli-proxy-api-plus
```

## 回滚思路（如果 latest 有问题）
1. 先从“升级前记录”里拿到旧的镜像 digest（`sha256:...`）。
2. 方式 A（推荐）：改 compose 里的 image 指定到该 digest（或 tag），再 `up -d --force-recreate`。
3. 方式 B：如果本机仍有旧镜像，直接用旧 digest 重建。

> 回滚需要具体旧 digest；务必在升级前记录。

## 本次实际执行记录（2026-03-16）
- 升级前镜像：`sha256:d2891a015b8cd36dbb41dd42123891233ea35046adeabfbfe5a6c7f3af394f3e`
- 升级后镜像：`sha256:5e3d600e10ab3c384ba1170bf67a35dedce1ddd35698f424fd3c000509a45581`
- 容器状态：`healthy`
- 日志版本信息：`CLIProxyAPI Version: v6.8.54-0-plus, Commit: cef2aee`
