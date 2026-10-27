# 制造工作台部署发现

审计日期：2026-10-27。范围为本地源码、文档与生产 SSH 只读检查；没有修改生产、启动容器、执行发布、读取凭据内容或使用浏览器。

## 已确认的生产基线

| 项目 | 实际值 |
|---|---|
| 域名 | `https://agent.orbbec.com.cn` |
| 主机 | `47.106.112.69`，文档规定的 SSH 身份为 `root` |
| 本地主线 | `AI-Agent-Platform/master`，`e5e07e40373803c66867347a144cebc59c14e00e` |
| 运行 API | `orbbec-agent-platform-platform-api-1` |
| API 源码补丁版本 | `d460d4521831c25a382a6fb9112fc079a9a6b14c` |
| API 镜像 | `sha256:900c41813f920ed7859de4fa87b381ea6f9e48b0c53d43298f0989b98a183547` |
| API 镜像标签 | `orbbec-agent-platform:sdk-knowledge-b11-d460d452-r3` |
| API 启动时间/状态 | `2026-10-23T13:42:00.709798852Z`；`healthy` |
| API 容器 ID | `dbe13dcf6f96ce14945e31e0ce85697a8bfaf5bfc446e4b8d2237e9372967c0f` |
| `current` 链接 | `/opt/orbbec-agent-platform/releases/2c6111bdefba4760cf67045dcdd2dc41333dc043`；不是 API 实际版本依据 |
| API 维护组合 | 37 份有序 Compose 输入，从运行容器的 `com.docker.compose.project.config_files` 标签取得 |
| 最后一个输入 | `/opt/orbbec-agent-platform/staging/sdk-knowledge-b11-20261023/overlay.json` |
| 权威维护文件 | 同目录 `future-maintenance.json`，字段 `compose_files_in_order` |

37 份输入的第一项仍为 `releases/184b7d86c7dd10765462c7caf424c4771067c532/deploy/cloud/compose.yaml`，随后保留 HR generation、全景、DAQ、SDK、Office、VOC、FAE 身份等覆盖。不能以主线 tip、`current` 或基础 Compose 自动重建当前平台。最新 SDK 维护记录还要求保留已验证的 Git 2.50.1 能力（`--no-lazy-fetch`、prefix `/usr/local`、sysconfdir `/etc`）及只读知识库挂载。

API 使用 UID/GID `10001:10001`、只读根文件系统、`cap_drop: ALL` 和 `no-new-privileges:true`。它已经加入 `orbbec-agent-platform-internal`、`orbbec-agent-platform-edge`、`orbbec-agent-platform-sdk` 和 `orbbec-agent-voc-extension`；其中 internal 地址为 `172.30.0.4`，DNS 别名为 `platform-api`。

本次基线中 API、loopback healthy；`platform-brain` 已显示 unhealthy，启动于 2026-09-28，属于发布前事实，本审计没有诊断或改变它。

## 无需修改 Nginx 的入口方案

生产文件 `/etc/nginx/sites-available/agent-domain.conf` 的 SHA-256 为 `ff83eb990c1f8a54d5825f77d43a1e643940428fb4933f23f822548872e36584`。第 950 行的 HTTPS `location /` 将未被其他专用 location 捕获的请求流式代理到 `http://127.0.0.1:8080`，读写超时均为 330 秒，关闭 proxy buffering/cache，清除外部 Authorization/Forwarded，并重写客户端转发头。

宿主机 8080 由 `platform-loopback` 绑定回环地址；`backend/app/cloud_replica/loopback_proxy.py` 是通用路径代理，目标为 `http://platform-api:8080`。因此 `/manufacturing/`、其资源和 `/manufacturing/api/*` 已能到达平台 API。当前匿名 HTTP 实测：`/api/health` 为 200；`/manufacturing/`、`/manufacturing/api/projects`、`/api/v1/account` 均为 401，且 no-store。401 只能证明现行身份边界，不能证明制造路由已经存在。

建议保持兄弟仓库独立：制造 Python 服务和 React 产物使用独立镜像、持久目录和 Compose project，服务只加入现有 internal 网络，不发布宿主机端口；平台只增加受控的同源入口代理和导航。这样平台 API 原有网络不需要变更，制造业务也不需要嵌入平台数据库或整个源码树。平台网关应在转发前执行已有 Session、CSRF、Origin 和明确授权策略；通过固定内部目标与专用服务凭据传递经过验证的主体，删除客户端伪造身份头，不把平台根路径 Session Cookie直接交给子服务。

另一可行方案是把兄弟项目的 Python router 和 React dist 作为明确版本的发布制品封装进平台镜像，但业务发布将与平台 API 进程耦合。不能仅挂载一个 ASGI app 就假设平台已有授权可自动覆盖其子路由。

现行 HTTPS server 的默认 `client_max_body_size` 为 `1m`。保持 Nginx 不变时，制造附件必须遵守单次请求限制，或设计小于该限制的分片；大文件一次上传需要另行明确审查入口大小配置。

## 身份与导航必须一起接入

平台身份边界失败关闭：匿名非公开路由 401；已登录但没有明确授权路由模板的请求 403。需要一起检查这些源码位置：

- `backend/app/control_plane/auth.py:44`：精确登录回跳路径和模式白名单。加入制造根入口和实际深链，避免登录后丢失上下文或开放任意回跳。
- `backend/app/control_plane/routes_auth.py:292`：已有认证应用 shell 的声明；制造入口应返回自己的构建产物或受控代理。
- `backend/app/control_plane/middleware.py:267`：公开静态 shell 白名单。若允许匿名加载登录壳，只允许固定壳/资源，业务 API 保持私有。
- `backend/app/control_plane/middleware.py:580`：认证、解析路由模板、授权、CSRF/Origin 链路；新的代理不能绕过它。
- `backend/app/control_plane/authorization.py:133`：明确的 authenticated self 路由集合，以及适用的制造业务授权。不要把任意 catch-all 路径自动授予所有人。
- `backend/app/main.py:1698` 与 `:1978`：路由组合及身份中间件构建。新路由须在中间件的路由解析视图内。
- `webui/src/platform/workspaces.ts`、`webui/src/panoramaNavigation.ts`、`webui/src/panoramaTypes.ts`、`webui/src/router.ts`、`webui/src/App.tsx`：工作台目录、首页导航和前端路由。导航须与实际账号权限和登录回跳契约一致。

已有 `/api/v1/internal/session/subject` 不是可直接公开使用的登录接口：生产 Nginx 明确拦截，服务端另外检查 loopback 来源并要求真实 Session；它只返回内部主体、显示名与 active 状态，不包含完整制造授权。不要为了独立服务接入而放开该公共入口。

## 发布机制与回滚依据

可以使用既有 SSH 方式：`ssh -i /Users/neo/.ssh/orbbec_aliyun_ed25519 -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes root@47.106.112.69`。不打印或复制密钥内容。`docs/runbooks/agentops-controlled-executor.md` 还记录了 `sudo -n -H -u agentops` 的本地受控执行身份及独立固定 known-hosts；本轮无需修改或重新安装它。

推荐沿用近期 API 限定发布模式：

1. 从已归并主线的准确提交生成独立变更制品；平台候选以当前精确镜像为基础，仅增加本次网关/授权/导航文件和必要 React 产物，核对文件摘要，保留其他已发布热修。
2. 从运行容器标签发现完整有序 Compose 链，保存每项摘要、运行环境/挂载/网络/安全配置、全部其他容器 ID、Nginx 文件与临时目录权限，以及相关页面和完整静态资源摘要。私有环境文件与数据库备份仅留在受控备份位置。
3. 在既有发布锁内生成候选 overlay；对完整组合做 `docker compose config --format json` 的程序化对比。只允许本次明确的 API 镜像/版本、制造目标配置或制造服务新增项变化；`PLATFORM_HR_AGENT_MODEL` 等原运行时变量须从当前事实继承，不能使用新源码默认值覆盖。
4. 先启动独立制造服务并验证持久化和内部 HTTP；再以完整旧链加本次 overlay 仅执行 `up -d --force-recreate --no-deps platform-api`。不重建 loopback/Brain/Office/HR/FAE/VOC/SDK。
5. 核对准确镜像、版本、health、身份/权限/CSRF拒绝、真实接口闭环、制品摘要、公网静态资源内容/MIME，以及其他容器和共享入口保持。页面验收由用户承担；不能使用匿名 200 或测试数量代替完整业务验收。
6. 失败时按原有有序链和同一运行时变量恢复旧 API 镜像；保留制造业务数据，停止或隔离新服务，记录失败证据。成功后写新的 `future-maintenance.json` 和生产版本收据。

可参考的已有机制：

- 仓库 `deploy/sdk/plan-only-rollout.md`：从容器标签保留完整 Compose 链、限定 API 切换和回滚的运行手册。
- 仓库 `deploy/sdk/overlay_guard.py`：运行环境与候选配置的失败关闭对比模式。该脚本专用于 SDK 字段，不能直接用于制造发布而放宽或伪造 SDK 值。
- 生产 `/opt/orbbec-agent-platform/staging/sdk-knowledge-b11-20261023/release.py`：已有 `prepare`（605）、`candidate`（762）、`rollback`（833）、`cutover`（850）、HTTP/静态内容、挂载和其他容器保持门禁。它是 SDK 专用脚本，只能阅读/提取模式，不能原样执行作为制造发布。
- 仓库 `deploy/cloud/deploy-input-lock.py` 与 `deploy/cloud/deploy.sh`：已有发布锁约定。通用 `deploy.sh` 会重建完整平台，当前叠加链不应直接调用。
- `docs/operations/2026-10-23-voc-observability-release.md` 和 `2026-10-23-fae-required-login.md`：近期精确镜像增量发布和受影响资源验证记录。

共享 Nginx 安全要求来自平台 `AGENTS.md`：生产禁止 `nginx -t -c` 或 `nginx -T -c` 独立配置测试。本方案不需要触碰 Nginx；若后续必须变更，先在隔离环境验证完整用户/临时路径边界，生产仅受控检查实际完整配置再重载。

## 尚未执行

制造程序开发、镜像构建、数据库/目录创建、平台接入修改、任何生产变更、真实模型调用和业务写入、已登录页面验收均不属于本次只读审计成果。发布前必须重新读取运行事实；以上容器 ID、镜像和 37 项链是审计时快照。
