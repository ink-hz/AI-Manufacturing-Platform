# OEM 急料批次②③实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复急料事实关联与岗位传递，完成发料标记、IQC 标记、MES 欠料源和实际 HTTP 数据流验收。

**Architecture:** 复用命令/对象注册、授权、幂等和既有 mock 集成族；派生查询不改账。未连接外部系统使用类型化 mock，平台运行真实 preview 服务。

**Tech Stack:** Python/FastAPI/Pydantic/SQLite/pytest/httpx。

## Global Constraints

- 新写入仅 OEM；急料/发料标记/派生待办不改库存、IQC、预留、需求或过账。
- schema 仍为24；支持真实23升级和已有开发24库的增量初始化。
- 不改 webui，不建真实外部适配器，不开 L3 写回，不自动关案。
- 集合钉点显式更新，不降低断言；实际 HTTP 服务与 mock 外部来源分别记录。
- 任务要求以修订后的 `docs/superpowers/specs/2026-11-09-oem-expedite-batch2-tasks.md` 为准。

## Task 1: 修复里程碑、一般责任待办与已检验提醒（Task 0+D）

**Files:** `workflow/expedite.py`, `workflow/service.py`；新增 `workflow/expedite_tasks.py` 如需隔离查询；`tests/workflow/test_expedites.py` / `test_expedite_tasks.py`。

**Interfaces:** 保持 `milestones(tx,pid,payload)` 与现有任务返回协议；提供有界急料任务查询并通过 service._actions 实时过滤。

- [ ] 写回归：改匹配后 A.arrival_at=None；其他工单/无工单/零实收/未解决争议不贡献 handoff_at；有效签收仍可读。
- [ ] 先运行上述测试观察失败，再修当前有效匹配、明确工单与正有效实收谓词。
- [ ] 覆盖开案前后一般待办、合格后标题变化、关案/撤权/只读消失、纯拒收与更正归零、50条边界、不动账。
- [ ] 使用 SQL LIMIT 和有效 IQC 视图派生，同案只一条，保持现有责任任务的截断语义。
- [ ] 运行专项测试、记录 RED/GREEN、提交并审查。

## Task 2: 发料四状态与 IQC 标记（A+B）

**Files:** 新增 `workflow/issue_marks.py`, `issue_mark_models.py`；修改 commands/contracts/expedite_schema/schema/store/service/api/supply；`tests/workflow/test_issue_marks.py`, `test_receipt_expedite_flags.py` 及动作钉点测试。

**Interfaces:** `issue.mark` 与 `issue_mark` 读者；现有项目 objects 路由新增仅 issue_mark 可用的 requirement_id 可选参数；SQL 过滤后分页和计数。

- [ ] 先写四阶段、乱序重复、双时间、未来/无时区拒绝、角色/OEM/跨项目、重启与不动账测试，观察预期失败。
- [ ] 三处注册动作/对象，写 append-only 事实；在 fresh、23→24 和已有24初始化 ISSUE_MARK_SCHEMA。
- [ ] 从提交56e2c51保存的真实 schema23 DDL建立升级夹具，验证原业务行不变；不得把24库改版本号伪造旧库。
- [ ] receipt 列表按本页 IDs 一次查急料关联，详情同标记；不改列表顺序/分页/总数。
- [ ] 验证按需求读取跨页、关案标记消失与无急料阴性样本，显式更新钉死集合。
- [ ] 运行专项与兼容测试、记录 RED/GREEN、提交并审查。

## Task 3: mock MES 欠料与来源投影（C）

**Files:** integrations/core_models/contracts/catalog/operations/core_mes/core_projections；必要时给 expedite.open_case 增加可信内部 source/object_id 参数；新增 integrations/test_mes_shortage.py，显式目录测试。

**Interfaces:** `mes.shortage` operation/fact，requirement_id/reason/impact；投影调用相同急料业务生命周期并保留 fact.source，原人工命令不接受客户端伪造来源。

- [ ] 先完整阅读 catalog、operations、core_mes、core_models、core_projections 与已存在 mes.inspect 的测试。
- [ ] 写源操作→事实→投影→open案测试；先失败，再补输入/事实联合类型、目录、策略、源迁移与平台投影。
- [ ] 验证相同 source key 重复投影与关案后重放不增案；不同事实撞在办需求拒绝；非 OEM/跨项目/撤权拒绝符合既有集成惯例。
- [ ] 每阶段检查账表和 authority 不变，来源详情为 mes/mock；显式更新操作清单，不修改生成的前端类型。
- [ ] 运行专项与集成兼容测试、记录 RED/GREEN、提交并审查。

## Task 4: 实际 HTTP 全链路、全量回归与交付（E）

**Files:** 新增 `scripts/verify_expedite_batch2.py`；验证记录 `.superpowers/sdd/expedite-batch2/e2e-walkthrough.md`；发布说明 `docs/oem-expedite-batch2-2026-11-09.md`。

- [ ] 使用现有构建产物执行 preview prepare/serve，启动独立回环 socket 服务，不调用 TestClient 代替 TCP 走查。
- [ ] 脚本用 httpx 请求 bootstrap/项目/commands/objects/tasks/integration API；依修订任务书 E 顺序保存关键状态、ID、来源和幂等结果。
- [ ] 对已存在 mock 数据流经 HTTP 验证 WMS/MES/SAP 原事实、投递及投影；来源为 mock，不声称外部真实接入。检查重启后读取与重复处理。
- [ ] 完整运行下列命令，确认零失败，再做全分支审查；将走查记录和报告复制到用户工作区可访问位置。

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/
```

- [ ] 按主题交付提交及验证结果，保持用户原材料不变；不部署或推送到生产。
