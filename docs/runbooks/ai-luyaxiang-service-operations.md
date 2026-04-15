# `ai.luyaxiang.com` 标准运维手册

这份文档是 `ai.luyaxiang.com` 的唯一标准运行手册，后续前后端启动、停止、更新、验活都按这里执行。

## 1. 目标与范围

适用对象：

- 前端仓库：`/Users/mac/Desktop/gago-cloud/code/doc-frontend`
- 后端仓库：`/Users/mac/Desktop/personal/doc-cloud/doc-ai-agent`
- 固定域名：`https://ai.luyaxiang.com`

适用场景：

- 启动服务
- 停止服务
- 重启服务
- 更新代码并发布
- 验证登录、聊天、健康状态

## 2. 当前线上链路

```text
Browser
  -> https://ai.luyaxiang.com
  -> Cloudflare Named Tunnel
  -> doc-frontend production server (127.0.0.1:5173)
  -> reverse proxy /api/auth/* and /api/chat
  -> doc-ai-agent backend (127.0.0.1:38117)
  -> MySQL (doc-cloud)
```

关键结论：

- `ai.luyaxiang.com` 线上前端不是 Vite dev server。
- 前端实际由 `doc-frontend/server/prod-server.mjs` 提供静态资源和 API 代理。
- 后端认证只使用 MySQL。
- Cloudflare 使用的是 Named Tunnel，不是 Quick Tunnel。

## 3. 代码与脚本的标准入口

### 3.1 仓库位置

- 前端：`/Users/mac/Desktop/gago-cloud/code/doc-frontend`
- 后端：`/Users/mac/Desktop/personal/doc-cloud/doc-ai-agent`

### 3.2 启动脚本

- 前端：`/Users/mac/.doc-cloud/bin/run-doc-frontend-vite.sh`
- 后端：`/Users/mac/.doc-cloud/bin/run-doc-ai-agent-backend.sh`

说明：

- 前端脚本名字虽然还叫 `vite`，但实际执行的是生产模式构建加静态服务。
- 不要把这个线上链路理解成 `npm run dev`。

### 3.3 launchd 服务标签

- `com.doccloud.system.doc-frontend.vite`
- `com.doccloud.system.doc-ai-agent.backend`
- `com.doccloud.system.cloudflared.named-tunnel`

### 3.4 日志位置

- 前端：`/Users/mac/.doc-cloud/logs/doc-frontend-vite.system.log`
- 后端：`/Users/mac/.doc-cloud/logs/doc-ai-agent-backend.system.log`
- Tunnel：`/Users/mac/.doc-cloud/logs/cloudflared-named-tunnel.system.log`

## 4. 认证标准策略

这是当前必须遵守的认证规则：

- 账号来源：MySQL `doc-cloud.auth_user`
- 会话来源：MySQL `doc-cloud.auth_session`
- 后端启动时只读取 `auth_user`
- 后端启动时不会自动插入、覆盖、重置 `auth_user`
- 登录成功后，运行时只会写 `auth_session`

当前固定账号为：

- `gago-1`
- `gago-2`
- `gago-3`
- `gago-4`
- `gago-5`

注意：

- 账号密码以 MySQL 表中现存数据为准。
- 服务启动不是账号初始化流程。
- 账号新增、禁用、改密属于单独的数据维护动作，不能依赖服务重启。

## 5. 标准启动

### 5.1 启动全部服务

```bash
sudo launchctl kickstart -k system/com.doccloud.system.doc-ai-agent.backend
sudo launchctl kickstart -k system/com.doccloud.system.doc-frontend.vite
sudo launchctl kickstart -k system/com.doccloud.system.cloudflared.named-tunnel
```

### 5.2 查看服务状态

```bash
sudo launchctl print system/com.doccloud.system.doc-ai-agent.backend | head -n 40
sudo launchctl print system/com.doccloud.system.doc-frontend.vite | head -n 40
sudo launchctl print system/com.doccloud.system.cloudflared.named-tunnel | head -n 40
```

### 5.3 查看端口监听

```bash
lsof -nP -iTCP:38117 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

## 6. 标准停止

```bash
sudo launchctl bootout system/com.doccloud.system.doc-ai-agent.backend
sudo launchctl bootout system/com.doccloud.system.doc-frontend.vite
sudo launchctl bootout system/com.doccloud.system.cloudflared.named-tunnel
```

如果只是临时重启，不建议优先用 `pkill`；优先用 `launchctl` 保持链路一致。

## 7. 标准重启

```bash
sudo launchctl kickstart -k system/com.doccloud.system.doc-ai-agent.backend
sudo launchctl kickstart -k system/com.doccloud.system.doc-frontend.vite
sudo launchctl kickstart -k system/com.doccloud.system.cloudflared.named-tunnel
```

## 8. 标准更新发布

这是以后更新到 `ai.luyaxiang.com` 的标准顺序。

### 8.1 更新前端代码

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-frontend
git pull --rebase origin main
```

如果前端依赖有变化，再执行：

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-frontend
npm install
```

### 8.2 更新后端代码

```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent
git pull --rebase origin main
```

如果后端依赖有变化，再执行：

```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent
/Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m pip install -e .
```

### 8.3 若启动脚本或 plist 改动，重新安装系统服务

```bash
sudo /Users/mac/.doc-cloud/bin/install-doccloud-system-services.sh
```

这一步仅在以下内容有变化时需要执行：

- `/Users/mac/.doc-cloud/bin/run-doc-frontend-vite.sh`
- `/Users/mac/.doc-cloud/bin/run-doc-ai-agent-backend.sh`
- `/Users/mac/.doc-cloud/system-plists/*.plist`

### 8.4 重启服务

```bash
sudo launchctl kickstart -k system/com.doccloud.system.doc-ai-agent.backend
sudo launchctl kickstart -k system/com.doccloud.system.doc-frontend.vite
sudo launchctl kickstart -k system/com.doccloud.system.cloudflared.named-tunnel
```

## 9. 发布后标准验活

### 9.1 本机后端健康检查

```bash
curl -fsS http://127.0.0.1:38117/health
```

### 9.2 本机前端健康检查

```bash
curl -fsSI http://127.0.0.1:5173
```

### 9.3 外部域名检查

```bash
curl -fsSI -H 'User-Agent: Mozilla/5.0' https://ai.luyaxiang.com
```

### 9.4 登录检查

```bash
curl -sS https://ai.luyaxiang.com/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"gago-1","password":"<PASSWORD>"}'
```

返回结果应包含：

- `token`
- `user`
- `expires_at`

### 9.5 当前用户检查

```bash
curl -sS https://ai.luyaxiang.com/api/auth/me \
  -H 'Authorization: Bearer <TOKEN>'
```

### 9.6 聊天接口检查

```bash
curl -sS https://ai.luyaxiang.com/api/chat \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <TOKEN>' \
  -d '{"question":"最近30天哪些地区虫情高"}'
```

## 10. 常用排障

### 10.1 页面能打开，但不能登录

先按顺序检查：

```bash
curl -fsS http://127.0.0.1:38117/health
tail -n 80 /Users/mac/.doc-cloud/logs/doc-ai-agent-backend.system.log
tail -n 80 /Users/mac/.doc-cloud/logs/doc-frontend-vite.system.log
```

再确认：

- `auth_user` 中账号存在且启用
- 输入的是 MySQL 中当前有效密码
- 不是误用了旧的 SQLite 凭证思路

### 10.2 页面能打开，但 API 失败

先检查：

```bash
curl -fsSI http://127.0.0.1:5173
curl -fsS http://127.0.0.1:38117/health
tail -n 120 /Users/mac/.doc-cloud/logs/doc-frontend-vite.system.log
tail -n 120 /Users/mac/.doc-cloud/logs/doc-ai-agent-backend.system.log
```

### 10.3 域名打不开

先检查：

```bash
curl -fsSI http://127.0.0.1:5173
sudo launchctl print system/com.doccloud.system.cloudflared.named-tunnel | head -n 40
tail -n 120 /Users/mac/.doc-cloud/logs/cloudflared-named-tunnel.system.log
```

### 10.4 确认 MySQL 认证表状态

```bash
mysql -u <USER> -p -h 127.0.0.1 -D doc-cloud -e "SELECT username, is_active, created_at, updated_at FROM auth_user ORDER BY username;"
mysql -u <USER> -p -h 127.0.0.1 -D doc-cloud -e "SELECT COUNT(*) AS active_sessions FROM auth_session;"
```

关键判断：

- `auth_user` 是账号真源
- `auth_session` 是运行态会话表
- 如果登录失败而 `auth_user` 正常，优先看密码是否已变更或后端日志是否报错

## 11. 禁止事项

以下动作不作为 `ai.luyaxiang.com` 的标准发布方式：

- 不要用 `npm run dev` 承载线上域名
- 不要把 Vite dev server 当成线上入口
- 不要依赖 SQLite 认证文件
- 不要期待重启后端会自动重建或覆盖 MySQL 用户
- 不要跳过域名登录和 `/api/chat` 验活

## 12. 一句话标准流程

以后更新 `ai.luyaxiang.com`，统一按这条链路做：

1. 拉取前后端代码
2. 需要时更新依赖
3. 需要时重装 launchd 服务
4. `kickstart` 三个 system service
5. 验证 `38117`、`5173`、`https://ai.luyaxiang.com`
6. 验证 `/api/auth/login`、`/api/auth/me`、`/api/chat`
