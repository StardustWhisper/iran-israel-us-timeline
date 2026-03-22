# Halo (Aliyun) Runbook — PostgreSQL 主库 / 可回滚

目标：
- Halo 以 **PostgreSQL** 为唯一真源（PG-only）。
- 具备：
  - 日常备份（workdir + PG dump）
  - 快速恢复（PG dump 恢复优先）
  - 极端情况下可切回 H2（仅最后手段）

> ⚠️ 本文不包含任何明文口令。PostgreSQL 口令统一从：`/root/.halo2/.pg-halo-password` 读取。

---

## 0. 关键位置（备忘）

- SSH：`root@101.200.132.24:5972`（key: `~/.ssh/aliyun.key`）
- Halo 容器：`halo`（端口：`8090`）
- Halo workdir：`/root/.halo2`
- PG 配置（容器侧读取）：`/root/.halo2/application.yaml`
- PG 密码（root-only 文件）：`/root/.halo2/.pg-halo-password`
- 备份目录：`/root/halo-backups/`

### H2 已禁用（防误回退）
- 归档：`/root/halo-backups/halo-h2-db-20260323_064740.mv.db`
- 禁用文件：`/root/.halo2/db/halo-next.mv.db.DISABLED-20260323_064740`
- 标记：`/root/.halo2/PG_ONLY.MARK`

---

## 1) 日常检查（30 秒）

```bash
# 容器是否在跑
docker ps --filter name=^/halo$

# 健康检查
curl -sS http://127.0.0.1:8090/actuator/health

# 首页（可选）
curl -sS -I http://127.0.0.1:8090/
```

---

## 2) 备份策略

### 2.1 Workdir 备份（全量兜底）
- 脚本：`/root/ops/halo_backup.sh`
- cron：`15 3 * * * /root/ops/halo_backup.sh >/root/ops/halo_backup.log 2>&1`

### 2.2 PostgreSQL dump（数据库兜底，恢复优先）
- 脚本：`/root/ops/halo_pg_backup.sh`
- cron：`25 3 * * * /root/ops/halo_pg_backup.sh >/root/ops/halo_pg_backup.log 2>&1`
- 上传：`r2halo:openclaw/backups/halo/aliyun`

### 2.3 本地保留策略
- 脚本：`/root/ops/halo_backup_retention.sh`
- cron：`40 3 * * * /root/ops/halo_backup_retention.sh >/root/ops/halo_backup_retention.log 2>&1`
- 策略：
  - workdir / pg dump：保留 14 份
  - h2-script：保留 30 份
  - 迁移临时目录：保留 30 份

---

## 3) 恢复（优先用 PG dump）

### 3.1 从 PG dump 恢复（推荐）

```bash
set -euo pipefail
PASS=$(tr -d '\n' < /root/.halo2/.pg-halo-password)
DUMP=/root/halo-backups/halo2-pg-YYYYMMDD_HHMMSS.dump

# 1) 停服务
docker stop halo

# 2) 重建库（用 postgres 用户，确保权限足够）
sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS halo;"
sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE halo OWNER halo;"

# 3) 恢复（custom format）
PGPASSWORD="$PASS" pg_restore -h 127.0.0.1 -U halo -d halo --clean --if-exists "$DUMP"

# 4) 启动并验收
docker start halo
sleep 20
curl -sS http://127.0.0.1:8090/actuator/health
```

> 备注：如果你不想 `--clean`，可改为“先 drop/recreate 再 restore 不 clean”。

### 3.2 从 workdir 备份恢复（全量兜底）
用于：workdir/附件/配置损坏等。

```bash
set -euo pipefail
TAR=/root/halo-backups/halo2-workdir-YYYYMMDD_HHMMSS.tar.gz

docker stop halo

# 强烈建议：先把现有 workdir 备份走
cp -a /root/.halo2 "/root/.halo2.bak.$(date +%Y%m%d_%H%M%S)"

# 解包覆盖（按你的打包方式可能需要调整路径）
mkdir -p /root/.halo2
# 示例：如果 tar 内就是 .halo2 的内容
# tar -xzf "$TAR" -C /root/.halo2

docker start halo
sleep 20
curl -sS http://127.0.0.1:8090/actuator/health
```

---

## 4) 从 R2 拉回备份并恢复（PG dump / workdir）

> 说明：
> - 本机（Aliyun）通常是“产备一体”，优先用 `/root/halo-backups/` 的本地备份恢复。
> - 如果本地盘坏了/误删了，则从 R2 拉回。
> - R2 remote 以当前实际使用为准：`r2halo:openclaw/backups/halo/aliyun`。

### 4.1 列出 R2 上的备份

```bash
# 列出目录（查看有哪些 dump / workdir）
rclone lsf r2halo:openclaw/backups/halo/aliyun --s3-no-check-bucket | tail -n 50
```

### 4.2 拉回一个 PG dump 并恢复

```bash
set -euo pipefail
PASS=$(tr -d '\n' < /root/.halo2/.pg-halo-password)
NAME=halo2-pg-YYYYMMDD_HHMMSS.dump

# 1) 下载到本地备份目录
rclone copy \
  "r2halo:openclaw/backups/halo/aliyun/${NAME}" \
  /root/halo-backups \
  --s3-no-check-bucket

# 2) 按 PG dump 恢复流程执行
DUMP="/root/halo-backups/${NAME}"
docker stop halo
sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS halo;"
sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE halo OWNER halo;"
PGPASSWORD="$PASS" pg_restore -h 127.0.0.1 -U halo -d halo --clean --if-exists "$DUMP"
docker start halo
sleep 20
curl -sS http://127.0.0.1:8090/actuator/health
```

### 4.3 拉回一个 workdir 备份并恢复（兜底）

```bash
set -euo pipefail
NAME=halo2-workdir-YYYYMMDD_HHMMSS.tar.gz

rclone copy \
  "r2halo:openclaw/backups/halo/aliyun/${NAME}" \
  /root/halo-backups \
  --s3-no-check-bucket

TAR="/root/halo-backups/${NAME}"
docker stop halo
cp -a /root/.halo2 "/root/.halo2.bak.$(date +%Y%m%d_%H%M%S)"
# 根据打包结构调整解包路径
# tar -xzf "$TAR" -C /root/.halo2

docker start halo
sleep 20
curl -sS http://127.0.0.1:8090/actuator/health
```

---

## 5) 极端回滚到 H2（最后手段，不推荐）
适用：PG 完全不可用且短期无法修复，同时必须立即恢复网站。

思路：把 H2 文件改回原名，并把 `application.yaml` 的 PG 配置移走/改回 H2。

```bash
set -euo pipefail

docker stop halo

# 1) 恢复 H2 db 文件名
mv /root/.halo2/db/halo-next.mv.db.DISABLED-20260323_064740 /root/.halo2/db/halo-next.mv.db

# 2) 移走 PG 配置（让 Halo 回到镜像默认 H2 配置）
#（也可编辑回 H2 r2dbc，但为了简单这里直接移走）
mv /root/.halo2/application.yaml "/root/.halo2/application.yaml.pg.bak.$(date +%Y%m%d_%H%M%S)"

# 3) 启动并验收
docker start halo
sleep 30
curl -sS http://127.0.0.1:8090/actuator/health || true
curl -sS -I http://127.0.0.1:8090/ || true
```

---

## 5) 常见现象
- 重启后短时间 `curl /actuator/health` 可能出现 `Empty reply` / `Connection reset`：属于启动窗口期（索引/插件初始化），稍等再测即可。

---

## 6) 关键安全约束
- 永远不要在聊天/文档/commit 里写入：PG 明文密码、R2 key、任何 token。
- 口令统一从 `/root/.halo2/.pg-halo-password` 读。
