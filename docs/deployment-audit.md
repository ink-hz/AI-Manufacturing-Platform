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

## 补充审计：已选定进程内模块与资产方案

2026-10-27 后续实现选择本报告列出的第二种可行方案：兄弟仓库的版本化 Python 模块和 React IIFE 资源，通过只读 `/opt/manufacturing` 挂载加载到平台 API 进程；制造 SQLite 使用独立持久挂载。这一选择取代上文“独立服务 + 平台代理”的实施建议，不增加服务间身份协议、Docker 网络或 Nginx 变更。本补充仍只读，未运行任何发布阶段或候选容器。

### 已核对的发布依据

- 现行 `future-maintenance.json` 的 `compose_files_in_order` 与运行 API 标签完全相同。该文件 SHA-256：`914a429a108f70c6f92a2bde98e4fd7e3df8304c27db4aabc240f5716e70d4fa`。
- 生产旧 `release.py` 与本地 `/tmp/manufacturing-release-template.py` 的字节一致，SHA-256：`fd7f0e42c2f7af0ca6f30b8bd1f4ff182d6b5f09f87c43a4f9ca39755df1f3e3`。
- 同目录 `deploy-input-lock.py` 的 SHA-256：`45c2d3fce8a5ef2e3dd6306eaa15b7cdbfc85072bed164033684f84b425a4eb4`。
- 当前运行依赖为 FastAPI `0.141.1`、Pydantic `2.13.4`、httpx `0.28.1`，满足兄弟包当前声明；不需要为了加载该包重新安装或升级平台依赖。
- API 没有 `/app/data` 或 `/app/data/manufacturing` 的现有持久挂载。只设置数据库路径会在只读根文件系统下失败；即使改变根文件系统可写，也不能获得容器重建后的持久性。
- 父任务另已核对五个拟改核心文件（`main.py`、`auth.py`、`middleware.py`、`authorization.py`、`routes_auth.py`）的线上字节与主线一致。这是五文件补丁的基线依据，不是全平台源码与主线相同的证明。
- 检查时 action/input 持久锁均不存在。这只是该时刻事实，发布程序仍必须非阻塞获取正式锁。

### 允许的精确运行差异

建议发布清单采用以下明确契约；若最终代码采用别的环境变量名，必须逐项替换为其真实名称和值，不允许以 `PLATFORM_MANUFACTURING_*` 整段前缀作为豁免。

| 字段 | 候选允许值 |
|---|---|
| `services.platform-api.image` | 本次平台补丁的唯一标签，构建与切换时同时固定镜像 ID |
| `PLATFORM_RELEASE_SHA` | 已归并平台主线的本次准确 40 位提交 |
| `PLATFORM_MANUFACTURING_ROOT` | `/opt/manufacturing` |
| `PLATFORM_MANUFACTURING_DATABASE_PATH` | `/app/data/manufacturing/workbench.sqlite3` |
| `PLATFORM_MANUFACTURING_RELEASE` | 已归并兄弟仓库的准确 40 位提交 |
| 新增代码 bind | 宿主机版本目录 `/data/orbbec-agent-platform/manufacturing/releases/<兄弟SHA>` → `/opt/manufacturing`，`read_only: true`、`bind.create_host_path: false` |
| 新增数据 bind | 宿主机独立目录 `/data/orbbec-agent-platform/manufacturing/state` → `/app/data/manufacturing`，`read_only: false`、`bind.create_host_path: false` |

四项环境差异中只有 `PLATFORM_RELEASE_SHA` 覆盖现有值，其余须验证原来不存在；若实际集成从固定代码常量获得 root/path/release，可省略相应新增环境项，不能添加无消费者的设置。保留原来全部环境值，包括 `SDK_KNOWLEDGE_*`、HR 模型选择、企业/外部身份、Office、DAQ、VOC 配置。无需修改全局 `PYTHONPATH`；固定包路径的显式加载应由受审查的接入代码完成。

预先创建宿主机目录，杜绝 Compose 静默创建错误目录。版本目录应由 root 控制，应用 UID/GID `10001:10001` 仅需读取/遍历；数据目录归该应用 UID/GID，建议 `0700`，必须允许创建 SQLite 数据库、`-wal` 和 `-shm`。不要递归改变既有平台目录的属主。不得挂载整个 `/app/data`，也不得让新挂载遮挡平台源码或现有 13 项挂载。候选有效 Compose 与运行验证都应按 destination 比较旧挂载，确保仅增加这两个唯一目标。

除镜像、上述精确环境字段与两项挂载外，平台 API 的 command、entrypoint、user、working directory、healthcheck、capabilities、只读根、安全选项、tmpfs、restart、全部四个网络及其固定 IP/网关优先级/别名等保持。全部其他服务配置应逐字等效。成功的新维护清单应为原 37 份有序输入加本次唯一 overlay；不更新 `current` 链接来伪装全量发布。

### 镜像与制品构建

候选镜像从已核对的运行镜像 **`sha256:900c41813f920ed7859de4fa87b381ea6f9e48b0c53d43298f0989b98a183547`** 派生，仅 COPY 明确批准的平台接入文件与必要导航产物；不从主线基础 Dockerfile重建整个运行环境，不执行 pip/apt 升级，不替换 Git、SDK知识文件或其他应用源码。保留镜像原 Cmd、Entrypoint、User、WorkingDir、Healthcheck、ExposedPorts 与现有自定义 Labels；镜像 ENV 若修改，只允许明确的发布标识。只改 Dockerfile LABEL 也会使既有严格 runtime label 门禁失败，应提前决定是否确有必要并明确审批差异。

兄弟制品从准确提交归档，至少固定包源码、`catalog.json`、React JS/CSS 与制品 manifest；不含 `.venv`、`node_modules`、测试数据或 SQLite 文件。核对整个只读树的相对路径、大小、SHA-256、模式、无 symlink，并在候选容器以 UID10001 验证实际可读取。制品上传、解包和候选测试期间不把版本目录当作可变工作目录；候选、切换前和切换后重新核对同一 manifest。

平台现有 source/static map 与兄弟代码/资产树必须分别取证。原旧脚本的 `maps()` 只扫描 `/app/backend/app`，不会覆盖 `/opt/manufacturing`，因此不足以证明兄弟制品部署正确。已有平台静态产物若因导航重建而变化，逐项列入批准差异；不能继续照用 SDK 发布“全部静态文件不变”的断言。

### 旧发布辅助函数的安全复用范围

旧脚本可以提供经过固定哈希的通用辅助实现，但不能执行它的 CLI、`prepare()`、`candidate()`、`cutover()` 或旧 `production_service_check()`。这些阶段硬编码了旧容器 ID、`8b91139c…` 镜像、`9926939e…` 版本、SDK index、SDK挂载和业务断言；直接改少量常量无法获得制造发布契约。

建议把审查过的通用函数显式复制到本次独立控制器，保留原来源哈希及函数清单，或者校验完整原文件哈希后导入并仅调用明确列出的通用函数。原文件 import 本身不执行 `__main__` 阶段；调用前所有依赖的全局常量必须指向本次私有 stage、准确平台提交和已固定 lock tool，不能向旧 SDK stage 写新收据。可复用的模式包括 `safe_path`、`file_tree`、私有输出的 `run/private_bytes/write`、`discover_files`、`actual_environment`、`compose`、`replay_equivalence`、锁实现和严格运行配置比较。制造 overlay/env/mount 对比、输入制品校验、候选业务检查和生产验证必须由本次控制器明确实现。

旧 `environment(api)` 会剔除调用者的 `PLATFORM_`、`COMPOSE_`、`SDK_` 环境，再仅从运行容器回填 `PLATFORM_HR_AGENT_MODEL`。保留这种隔离原则，用同一干净环境渲染 baseline/candidate、执行 up 和 rollback；若本次变量采用其他前缀，也应明确清除它们。不要把全部运行环境导回 shell 来掩盖 Compose 漂移，更不要把凭据打印到日志。渲染后的 baseline 环境必须与真实运行值相等，镜像默认环境也须纳入后述 replay。

旧脚本的三个锁分别是宿主机 `.deploy.lock` flock、`private/agent-brain-action.lock` 及 `private/deploy-input.lock`。prepare/candidate 使用前两项；真正切换阶段还获取 deploy-input 锁。每个阶段释放后，下阶段须重新核对容器 ID、完整链、配置/脚本/制品摘要；不能沿用早先读取的状态直接 up。切换失败按同一环境与原链恢复；仅在明确确认回滚成功后释放锁。回滚不确定时保留持久锁和私有失败收据，不能在 finally 中强制删除别人的锁。

旧 `replay-defaults.private.json` 固定的是旧 `8b91139c…` 镜像，**不能沿用**。本次须为当前 `900c4181…` 镜像建立新的、从未启动、无挂载、无外加环境、`--network none` 的 Docker defaults probe，固定其 inspect 与镜像 Config；再使用严格 `replay_equivalence` 证明原 37 份 Compose 和干净环境可以重建当前 API。该 mapper 只允许已审查服务字段，对未知字段应失败。其 null/空数组标准化只适用于已经解释过的 Docker 空值编码，不能删除有实义的差异。新挂载使用 `create_host_path:false` 的语义不应被放宽为 true。

这项新 replay 证明是回滚可重现的前置条件。候选镜像及当前旧标签都要核对其不可变 image ID；baseline replay、候选有效配置比较通过后才允许 `up -d --no-build --no-deps --force-recreate platform-api`。单纯 `docker compose config` 通过不证明与运行容器一致。

### 无员工冒用的候选和生产验收

候选正向业务验证放在隔离容器：固定目标镜像与只读兄弟制品，`--network none`、只读根、UID10001、drop ALL/no-new-privileges；仅挂载独立一次性数据目录，不挂载任何生产凭据、数据库、SQLite或身份 Cookie。使用明确标注的合成 AuthContext/授权存储，通过真实中间件和本次 router 运行 HTTP，覆盖允许/拒绝、read-only、CSRF/Origin、失效身份、未知资源、乐观冲突、幂等、输入保存与任务状态；删除进程并用同一一次性目录重新启动，核对保存结果还在。禁止调用完整生产 lifespan 来做这项合成验证，防止启动目录同步、Brain或外部提供方。

当前兄弟 `Repository` 构造不触碰数据库，但其 `health/read_stage/overview` 第一次连接会设置 WAL、创建目录和表。不能把这几个方法称为对生产数据库的“纯只读检查”。部署初始化若使用它们，必须明确仅创建制造自有空 schema，不创建虚构业务记录，并单独报告；本次审计没有执行。

生产阶段可以在没有员工 Cookie 的情况下确认：平台健康、匿名业务 API401、未登录壳进入既有登录契约、精确 MIME/缓存策略、全部代码/制品摘要、两个挂载及 UID权限、原有业务入口/静态摘要、旧服务和 Nginx边界保持。容器内模块/目录/资产校验与制造自有存储初始化不需要冒充任何主体，也不能据此声称已登录正向权限通过。不要导出现有 Session、制造生产身份、写合成员工会话，或在实际生产进程注入伪造 AuthContext 来填补正向验收。用户真实登录后完成工作台页面验收；若尚未进行，生产收据明确写 `authenticated_browser: not_run`，并把隔离候选合成身份验证、生产匿名边界验证和真实用户验收分别报告。

回滚平台镜像和挂载组合时保留制造 state 目录；不能删除已产生的真实数据。如果后续需要备份已活动的 SQLite，采用其在线 backup 接口或在停止写入后完整处理 DB/WAL，不能只复制单个 `.sqlite3` 文件声称完成一致性备份。
