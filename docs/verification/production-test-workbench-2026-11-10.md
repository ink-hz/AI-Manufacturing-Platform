# 产测管理工作台实现与验证记录

日期：2026-11-10。状态：F1–F5 及增量 R6／R7 均已修复并通过最终独立审查，两个仓库已归并本地主线，合并后构建与定向 HTTP／宿主检查通过；未推送、未部署。浏览器页面验收依宿主 `AGENTS.md` 由用户承担。

## 对象与代码

产品契约：[产测工作台设计](../superpowers/specs/2026-11-10-production-test-workbench-product-design.md)。首期继续仅当前平台管理员可使用；负责人、工程师、PE 是任务视角，不是新增授权角色。个人草稿仅所有者可见，固定交接可由当前有权管理员恢复；接手产生个人分叉。

- MF：调查服务 `a1102ee`，原生聚合 `83cad73`，前端最终修正 `6aef6f5`；本轮后台／HTTP 修正 `990ea879d2cb1c655012049a62bcacfe3d7bf8cc`（基线 `440ec28`）。
- PF：宿主集成 `f8f362596ed81cac8360c0aa202acb545509ea21`（基线 `57060de1`）。
- 本记录同提交包含最终 F1–F5 边界修正：查询归属、精确／缺失编辑、异步采纳、日志捕获选择及连续操作保护；PF 和源 SQL 未改变。
- 最终审查及程序归并基线：MF `e01d275ed1b8395568949373a9f45e5124619dff`（本地 `main`），PF `f8f362596ed81cac8360c0aa202acb545509ea21`（本地 `master`）。后续交付记录提交只改文档。

宿主精确登记 21 个方法／路径：原有九条读取、三条聚合／可用性读取、九条调查与交接操作。包含 17 GET、3 POST、1 PUT；未知方法、路径及尾缀没有新增通配放行。缺失接口按方法和路径分别保留，较旧或部分升级的发布不会因缺 POST／PUT 而遮挡已存在的同路径 GET。不可用产测接口仍要求管理员并返回私有 `no-store`；正常制造工作流不依赖可选产测连接成功。

派生调查库路径在采用连接前与旧制造库、工作流域库、授权库、快照库和私有配置隔离，拒绝同路径、符号链接和硬链接别名。原生协议继续为 2，公开工厂保留两个参数，原有五个 `ProductionToolsConfig` 位置参数兼容；本轮没有引入自定义路径配置入口。

## 实际契约

`context.history_sn` 为可选的 1–200 字符严格文本，与 `history_range` 一起保存独立 SN 履历查看对象。它不进入源查询或影响面过滤，不替代原 `context.sn`，不改变主要事件一致性。草稿、固定交接和接手分叉均保留该字段；仅修改履历对象／视图／备注不重算已保存影响数。

对照事件允许软件版本、配置日志 ID 和配置版本不同，包括原症状选择“版本／配置缺失”的情况。原问题过滤继续保留，主要事件校验没有放宽；项目、来源、环节和工具约束仍在。

草稿及交接的复查响应必含仅服务端输出的 `binding`：

```json
{
  "kind": "draft",
  "id": "00000000-0000-4000-8000-000000000001",
  "version": 2,
  "primary_selection_id": "00000000-0000-4000-8000-000000000002",
  "comparison_selection_id": null
}
```

示例仅表示类型，不是源数据。`kind` 为 `draft` 或 `handoff`，`id` 与 `version` 来自实际参与复查的保存内容，两个选择 ID 来自该内容（无选择时为 null）。另一标签页已保存后，复查返回实际新修订；复查中又发生更新时不会把先前已解析的内容标成之后的修订。客户端不能提交或覆盖此字段；前端不采纳缺失或不匹配的绑定。

日志选择保持 `logs` 最多 5 项，兼容十进制字符串 ID，并新增严格的捕获定位输入：

```json
{"logs":[{"snapshot_id":"00000000-0000-4000-8000-000000000001","offset":0,"source_log_id":"42"}]}
```

`offset` 必须为 0–999 的整数；混合形式按源日志 ID 去重，额外字段、布尔偏移和数值 ID 均拒绝。服务器校验当前项目／来源、证据类型、位置及行 ID，从不可变捕获派生允许的描述、指纹、读取时间和真实过滤条件；客户端不能提供可信描述、过滤条件、URL 或指纹。保存窄查询或源 keyset 后续页中的候选不重扫原问题的较宽范围。已有引用以 ID 保留时复用其可信元数据，新 ID 仍走原有有界查找。捕获中的 `before_id` 在公开元数据中继续为精确十进制字符串。

每个引用独立保存自己的日志范围、显式 CSN、上位机／审核单／工具条件和 continuation anchor；复查先复用有效捕获，过期后只按该引用原条件做一次有界源查询，并在截断、缺失、歧义和不可用时分别报告。当前候选搜索是查看状态，不会重标或移除旧引用；原问题范围仍独立，替换主要事件仍清空对照和日志。日志关联继续为“待核对”，不从事件 SN 推断 CSN。日志内容下载协议未改变。

前端在导航边界按有效查询退役旧游标，显式重新查询（包括相同 SN）及重新读取获取新捕获；同查询分页和返回精确历史位置保留捕获。增量复审 R6 修正为显式读取代际进入生产／过站两个履历消费者，保证第一页与已分页状态的同 SN 提交都重新读取。精确与缺失编辑共享规范化操作；R7 将一次编辑原子化为先清理旧依赖，再施加该次编辑明确选择的全部精确／缺失父子条件，变更对象会清理依赖版本及对应缺失条件。读取交接、另存、生成交接及冲突重读均受对象和编辑／导航代际约束；自己的保存确认仍推进修订并保留更新的待存备注。日志在途保存时明确禁用添加／移除，失败后的后续操作使用已确认加待存的有效集合。

## 本地验证

| 范围 | 结果 | 证据边界 |
| --- | --- | --- |
| 本轮 MF 原生模块及通用 API | 447 通过，0 失败／跳过／pytest 警告，13.48 秒 | 含原生 SDK 检查、持久化、解析绑定、所有产测 API、真实本地 HTTP 进程 |
| 本轮 PF 制造集成四组 | 221 通过，0 失败／跳过／pytest 警告，11.04 秒 | 旧版／部分发布、精确路由、授权、路径别名、可选连接故障隔离 |
| Task 3 最终前端定向组件 | 已记录 84 通过，0 警告／跳过 | `6aef6f5`；本轮未重复执行 |
| Task 3 最终 TypeScript／Vite／IIFE 检查 | 已记录通过 | 111 模块；本轮未重复构建，最终主线包由根任务核验 |
| Task 4 时组合通用前端 | 37 文件／391 通过，0 警告／跳过，29.07 秒 | MF `990ea87`、PF `f8f36259`；专用 E30 显式排除并未执行 |
| F1–F5 最终 MF 原生模块及通用 API | 462 通过，0 失败／跳过／pytest 警告，11.28 秒 | 同提交；含实际 loopback Socket 捕获选择／旧 ID 保留、窄查询／keyset、有界复查和严格拒绝 |
| F1–F5 最终前端组件及既有 API／导航／壳层 | 5 文件／104 通过，0 警告／跳过，4.87 秒 | 同提交；20 项新回归覆盖实际控件、请求体和最终保存引用 |
| F1–F5 TypeScript／Vite／IIFE 检查 | 通过 | 111 模块；640.16 kB JS（gzip 185.17 kB）；无浏览器自动化 |
| R6／R7 最终前端组件及既有 API／导航／壳层 | 5 文件／111 通过，0 警告／跳过，4.80 秒 | 追加 7 项实际控件回归；含第一页／已分页同 SN 两源重读、父子精确／缺失组合和持久化 |
| R6／R7 TypeScript／Vite／IIFE 检查 | 通过 | 111 模块；640.46 kB JS（gzip 185.25 kB）；仅前端变更，未重跑后台／PF／SQL |
| 最终组合通用前端 | 37 文件／418 通过，0 警告／跳过，29.06 秒 | MF `e01d275e`／PF `f8f36259`；E30 按既定 runbook 排除，仍未执行 |
| 合并后原目录 TypeScript／Vite／IIFE／CSS | 通过 | 原目录重新构建，111 模块；JS 640,463 字节、CSS 38,503 字节，与已审查包 SHA-256 相同 |
| 合并后真实本地 HTTP 进程 | 2 通过，4.08 秒 | MF `main` 使用 PF `master` 的实际路径；显式合成身份／源边界不变 |
| 合并后平台产测路由／授权／路径隔离 | 35 通过，1.79 秒 | PF `master` 从 MF `main` 加载发布；0 跳过／警告 |

本轮使用 PF 工作树的 `.venv/bin/python`，设置 `PYTHONPATH=src` 和 `TEST_PLATFORM_SOURCE_ROOT=/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform`，执行 `python -m pytest tests/production_tools tests/test_api.py -q`。前端在 `webui` 执行 `npm test -- src/workflow/productionTools src/workflow/api.test.ts src/workflow/navigation.test.tsx` 和 `npm run test:bundle`。较早记录仅代表其对应提交。后续两次前端修正后按新代码执行通用回归，最终为 418 项；未重复无变化的 PF 221 项和实际源 SQL 探针。

真实 loopback HTTP 使用实际 uvicorn 进程、PF `IdentitySecurityMiddleware`／`AuthorizationService` 和 Cookie、Origin、CSRF 检查。测试身份会话、只读审计边界、时间及原生固定 SELECT 读取器为显式合成边界；未接触真实员工账号或实际源连接。直接加载 MF 路由的进程验证与 PF 发布加载／精确登记测试分别覆盖各自责任。

走查：管理员 A 保存主要事件、不同版本对照及日志 → 另一标签页更新并复查实际修订 → 生成不可变交接 → 管理员 B 恢复并另存 → 原 A 后续更新不改交接 → 有效快照过期后重复候选保持歧义 → 当前管理员降级／会话撤销被拒绝 → 同存储重启但来源修订改变返回 404 → 30 天到期返回 410。另含版本缺失症状的实际 HTTP 保存、无主要事件直接 SN 履历保存／交接／分叉及影响面不变。普通成员不能恢复链接；只读管理员可读交接但不能保存、生成交接或另存。错误 CSRF／错误 Origin 被拒绝，所有结果保持 `no-store`。

## 主线整合与最终核验

最终独立整分支复审结论为 `Ready to merge: Yes`，F1–F5、R6／R7 均关闭，无剩余发现。随后 MF `main` 从 `09a8e8d` 快速前进至 `e01d275e`，PF `master` 从 `57060de1` 快速前进至 `f8f36259`，没有重置、覆盖或清理其他工作。归并前已核对远端跟踪基线没有领先的远端提交；本次不推送、不部署。原 MF 工作区三处既有修改的补丁 SHA-256 在归并前后相同，未跟踪资料未被清理。

最终通用前端在已审查功能树执行既定 `npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx`，设置 PF 依赖环境的 `WORKFLOW_TEST_PYTHON`；418 项通过。原目录 `webui` 重新执行 `npm run test:bundle`。合并后的两项后端检查分别为：

```sh
WORKBENCH_MF_ROOT=/Users/neo/Developer/work/AI-Manufacturing-Platform
WORKBENCH_PF_ROOT=/Users/neo/Developer/work/AI-Agent-Platform/.worktrees/admin-home-20261109
WORKBENCH_TEST_PYTHON=/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform/.venv/bin/python
(
  cd "$WORKBENCH_MF_ROOT"
  TEST_PLATFORM_SOURCE_ROOT="$WORKBENCH_PF_ROOT" PYTHONPATH=src "$WORKBENCH_TEST_PYTHON" -m pytest -q tests/production_tools/test_socket.py
)
(
  cd "$WORKBENCH_PF_ROOT"
  TEST_MANUFACTURING_RELEASE_ROOT="$WORKBENCH_MF_ROOT" PYTHONPATH=backend "$WORKBENCH_TEST_PYTHON" -m pytest -q backend/tests/test_manufacturing_production_tools.py
)
```

这里的 Python 是已安装 PF 锁定依赖的隔离解释器；两个来源根目录均使用归并后的真实本地路径，没有继续指向旧功能分支。JS／CSS 与已审查构建逐字节一致：

- `manufacturing.js`：`7887db071e3de52af43dd9c182c37623885b47f0539d75cd284b63bc801881c7`
- `manufacturing.css`：`e30ca34be3615cbd4a7ad74af2b44ed686114a273c0f10290b9ed74213032954`

此处确认的是本地主线代码、资产和所列接口检查，服务进程及生产发布没有被重启或替换。

## 实际源读取的独立证据

根任务已在 `7d0b74c` 对 Source-A/B 分别验证 17 例／28 条注册 SELECT；又在 `83cad73` 分别验证受影响的 11 例／27 条 SELECT，含各概览块时间范围、正值最早事件时间、七类缺失字段谓词、组合缺失条件和缺失设备日志。31 天有界 FAIL 分组在两源均有正值且完整。窄窗缺失群体为空，仅证明 SQL 执行与范围，不冒称正值缺失群体业务验收。

上述证据使用原生固定 SELECT 编译器、受限读取和超时。源名仅为匿名标签，不断言它们就是生产部署数据源。本轮仅变更调查元数据和宿主边界，未改变 SQL，故未重复读取实际源。实际源结果不代替本地身份／HTTP 证据，本地合成读取器也不代替实际源结果。

## 仍未执行

真实员工／钉钉登录、真实岗位自助授权、浏览器刷新／布局／交互验收、专用 E30、生产部署与生产业务闭环均未执行。本轮没有部署、没有开放普通岗位访问、没有源写入、旧 Go 初始化、外部业务消息或私有配置／源行／对象地址输出。

本记录说明代码和接口证据，不能称为已上线、整体可用或生产验收通过。版本组合专题、完整跨项目 SN 搜索、FPY／OEE、自动根因及生产放行仍在首期范围外。
