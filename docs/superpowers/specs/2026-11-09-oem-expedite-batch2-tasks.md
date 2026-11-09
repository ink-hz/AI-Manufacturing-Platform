# 任务书：急料主线批次②③——发料四状态、IQC 急料标记、mes.shortage、入库待办

日期：2026-11-09。执行者：Codex。依据：已接受的[急料主线设计](2026-11-09-oem-expedite-design.md)（§3.3、§3.4、§3.5）与[平台开发启动计划](../../platform-development-launch-plan-2026-11.md) §1 业务链层。批次①（material_expedite 生命周期＋推导里程碑，schema24）已于今日完成并合入 main（commit `24d5bcb`），本任务书在其之上继续。

**修订授权**：用户要求根据复审同步修改架构、目标材料和任务书并开始开发、进行真实 HTTP 数据流接口测试；尚未打通的系统使用 mock。本修订明确替代初稿中的 IQC 置顶、检验等同入库及走查顺序口径。

**范围外（不要做）**：前端（批次④另立任务）、真实 SAP/WMS/MES 适配器、急料分级、自动关案、独立推送通道、L3 写回。设计未授权的新对象/新导航一律不加。

---

## 0. 必读的仓库纪律（本轮已踩过的坑，照办可省半天）

1. **新动作必须三处登记**：`commands.py` 的 `WorkflowAction` Literal 清单（否则 `literal_tag` 在 import 时直接抛错）、`COMMAND_REGISTRY.register`、新对象还要加 `contracts.py` 的 `ObjectKind` 枚举。
2. **钉死清单测试必须显式更新**（这是仓库防静默膨胀的纪律，不是测试写死了）：
   - `tests/workflow/test_a1_extensions.py` — 注册表动作全集（显式字符串集合）
   - `tests/workflow/test_admin_full_access.py:62` — allowed_actions 集合；上下文化动作（OEM-only）要加进排除集
   - schema 版本钉点：`test_material_handoffs.py`（==24）、`test_authority_assistance.py`（SCHEMA_VERSION==24）、`tests/workflow/integrations/test_profile_migration.py`（==24，future 探针现为 25）、`test_core_compatibility.py`、`test_operation_boundary.py`
3. **schema 决策：留在 24，不开 25**。schema24 尚未发布（生产在 23），新建 `ISSUE_MARK_SCHEMA` 常量，fresh schema 与 23→24 迁移都执行。已经运行批次①的开发/preview schema24 库也须幂等补齐该表，不重建数据、不改版本。补冻结的真实 schema23 DDL/业务行直接升级测试；不能只把新建24库改版本号冒充23库。
4. **实现模板**：`material_handoffs.py`（写路径＋authorize＋角色）、`expedite.py`（批次①，含 OEM applicable 复用、`actor_fact`/`trusted_name` 复用）、`arrival.py`（纯事实对象＋`laboratory.insert`）。通用件：`orders.own`（归属校验）、`quality.fail`（默认 409，显式 422=INVALID_COMMAND）、`laboratory.business/canonical/stamp/insert`、`authority.register_reader`。
5. **service.py 两处挂点**：①`~L361` allowed_actions 的 OEM 过滤（已是 `startswith(("material_handoff.", "expedite."))`，新前缀往元组里加）；②`~L1005` authorize 钩子簇（`material_handoffs.authorize` / `expedite.authorize` 旁边加新模块的）。模块本身要加进 service.py 顶部的注册 import 列表。
6. **测试夹具**：`workflow` fixture 全真 HTTP。`w.material_requirement(mode="oem", qualified="80")` 一步造出项目+需求+承诺+收货+IQC（`qualified="0"` 则无收货无检验）；`w.command(pid, action, actor_name=..., expected_status=...)`；`USERS` 固定身份；不动账断言照抄 `test_expedites.py::accounting`。
7. **运行命令**（仓库根目录）：
   ```sh
   PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_expedites.py <新测试文件>
   # 收尾必须全量：
   ... -m pytest -q tests/
   ```
   基线：**1142 passed / 35 skipped，零失败**。收尾时全量必须回到零失败。

---

## Task 0：先修批次①有效事实与责任待办

- arrival 里程碑只采用各观察的最新匹配，更正到其他需求后旧需求不再计入；多个有效观察取发生时间最早者。
- handoff 里程碑要求 `h.work_order_id` 明确等于需求工单、实收量大于零、状态为 `received` 或 `resolved`；其他工单、无工单、零实收和未解决争议不计入。多个有效签收取最早发生时间。
- 所有 open 案从开案起对 warehouse/supply/production/project_owner 形成一般责任待办，不等待 IQC；只读、撤权、无关角色不可办理。任务 D 是同一待办的标题变化，不生成重复待办。
- 保留原始里程碑时间。本批不新增时长计算接口；未来展示按设计 §3.2 区分开案前已有事实、缺失与逆序，不显示负等待时间。
- 回归覆盖四个复审反例、正例、分页界限、撤权/只读及逐步不动账。

## Task A：发料四状态 `issue.mark`（设计 §3.4）

P13 的人工登记验证版。每笔标记是一条不可覆盖的事实对象。

- **命令** `issue.mark`：字段 `requirement_id: UUID`、`stage: Literal["printed","picked","receipted","posted"]`、`note: Text | None = None`、`occurred_at: AwareDatetime | None = None`（默认业务时钟，不得晚于 now；显式时间须带时区）。
- **约束**：需求归属同项目；仅 OEM 项目（authorize 同 expedite 模式）；**允许乱序与重复 stage（补录是一等公民）**——不校验 printed→picked 顺序，只如实留痕；不改库存/预留/IQC/过账（不动账断言必测）。
- **角色**：`{"warehouse", "supply", "production", "project_owner"}`。
- **对象** `issue_mark`（ObjectKind 新增）：表 `issue_marks`（seq 自增、id、project_id、requirement_id、work_order_id、stage、payload_json；索引 `(project_id,seq)` 与 `(project_id,requirement_id,seq)`）。payload 含 actor 快照（复用 `actor_fact`）、occurred_at/recorded_at 双时间、manual SourceRef（模式照 `expedite.open` 的 source dict）。
- **读**：`register_reader`；summary 标题含 stage 与物料；relations 指向 requirement 与 work_order。现有项目对象列表增加可选 `requirement_id: UUID`，仅用于 issue_mark，归属校验后 SQL 过滤再计数/分页；不新增端点或聚合接口，不全表拉取后在 Python/前端过滤。其他 kind 携带该参数拒 422。
- **测试**（新文件 `tests/workflow/test_issue_marks.py`）：四个 stage 各标一笔并乱序补录一笔历史时间；非 OEM 拒 422；无权角色拒 403；跨项目需求拒；不动账；occurred_at 晚于 now 拒 422；重启后可读（可并入现有 restart 模式或独立断言）。

## Task B：IQC 待检的急料标记（设计 §3.3，纯读侧）

- **位置**：`supply.py` 的 receipt 分页分支（`_page` 内 `kind == "receipt"`，约 L1003）与 receipt 详情（`_detail`）。
- **做法**：该收货的 commitment→requirement 若存在 `state='open'` 的 material_expedite，则 summary 的 `blocking_reasons` 追加一条 `"Expedited: open expedite on linked requirement"`（放首位），详情同。**不改排序、不碰分页约定**（有界查询纪律）。前端后续可在当前页分组，不声称全局置顶；跨页优先级另立契约。
- **实现提示**：分页分支里避免 N+1——用一条针对本页 receipt ids 的 IN 查询或 EXISTS 子查询并入现有 SQL。
- **测试**：开案后 receipt 列表/详情带标记；关案后标记消失；无急料项目不带；列表顺序与无标记时完全一致。

## Task C：`mes.shortage` 模拟源操作（设计 §3.5，I5 预埋）

让 mock MES 能发布"工单欠料"事实，消费后在平台开急料案，来源证据走既有链路。

- **先研读**（勿跳过）：`integrations/catalog.py` 的 `OperationSpec` 与现有 `mes.*` 条目、`integrations/operations.py` 的 `FactPolicy` 映射（现有样例：`"wms.qualification": FactPolicy("supply.inspect")`）、`integrations/core_mes.py` 的 `prepare/transition/consume_fact`、`integrations/core_models.py` 的输入模型模式。照最简单的既有 mes 操作（如 `mes.iqc`）依样画葫芦。
- **新增**：输入模型（core_models，含 requirement 定位与 reason/impact 文本）；`catalog.py` 条目 `"mes.shortage"`（system="mes"，输出 fact type `"mes.shortage"`，underlying_action="expedite.open"）；`operations.py` FactPolicy 映射 `"mes.shortage": FactPolicy("expedite.open")`；core_mes 的 transition 产出该事实。
- **边界**：消费产生的 expedite 与人工开案同对象同生命周期，SourceRef mode=mock、system=mes；**D-e 约束仍生效**——同需求已有在办案时，消费侧的行为参照既有事实消费对重复/冲突的处理惯例（研读后遵循，不自创）。
- 相同 source key 的重放返回原投影；关案后重放也不得重开。不同事实遇到已有 open 案应按现有业务拒绝惯例处理，不能吞掉冲突或改变 D-e。必须接入 OperationPayload/FactPayload 联合类型、校验/投影及来源证据，不能仅增加目录项而没有平台效果。
- **测试**：放 `tests/workflow/integrations/`，照该目录现有 mock 操作测试的结构：源操作→投递→消费→平台出现 open expedite 且 source 显示 mes/mock；重复投递不重复开案；非 OEM 项目的行为与既有集成对 422 类拒绝的惯例一致。
- **钉死清单注意**：integrations 目录下若有操作目录全集/数量断言（搜 `OPERATIONS` 相关测试），显式补入 `mes.shortage`。

## Task D：急料已检验责任提醒（P10 协同准备，非 WMS 入库证明）

- **先研读**：`service.py` `_tasks`（L503 起）现有任务派生模式与 `material_handoffs` 的待办归属实现（接收待办归接收人那套）。
- **规则**：Task 0 的一般责任待办在同需求有效 IQC 合格量大于零后，对 production/supply 改标题为“急料已检验，待安排上线/关案”；仍指向同一 expedite，不重复生成。next_actions 经现有角色过滤为 expedite.close 或 expedite.progress；关案后消失。其他责任角色仍见一般待办，纯拒收 IQC 不触发已检验提醒。
- 本任务只表示有正合格量，不证明上架、可用库存或已上线。WMS 入库完成另按 I3 回执验收，未打通的 WMS 在数据流测试使用既有 mock。
- **纪律**：派生只读不落库；不越权暴露动作（撤权/只读后不可见）；分页有界。
- **测试**：IQC 前一般待办→正合格量后标题变化→关案消失；纯拒收、来源更正归零、生产/供料/仓库角色、无关角色、撤权、只读、分页与不动账。

## Task E：真实端到端验证（完成 A–D 后）

1. **全量后端**：`pytest -q tests/` 零失败（基线 1142+新增）。
2. **真实服务走查**：用 `scripts/preview_manufacturing.py`（先读脚本用法）起本地真实服务，以 HTTP 实际走一遍完整链路并留存输出：
   建项目(OEM)→需求/承诺→**开急料案并确认一般责任待办**→到货观察→收货→匹配→IQC→**确认 receipt 急料标记（Task B）及已检验提醒（Task D）**→交接签收→**issue.mark 四状态各一笔并按需求分页读取（Task A）**→详情确认五里程碑→关案、标记/待办消失→**mock mes.shortage 再开一案（Task C）**→重复查询/投影不增案，确认 mes/mock 来源。另走既有 mock WMS/MES/SAP 事实链，记录源接受、因果投递、业务投影及过账证据各自状态，不能互相替代。
   每步的 HTTP 响应关键字段记入走查记录。
3. **交付物**：代码分主题提交（Task 0+D、A+B、C，或按耦合拆分，信息注明验证）；walkthrough 记录存 `.superpowers/sdd/expedite-batch2/e2e-walkthrough.md`，附可重跑脚本和脱敏关键响应。明确 socket 服务实际地址、命令、时间、源系统 mock 边界与退出状态。Task 0 修复及本次口径已由用户授权同步设计；若出现新的冲突，报告而不自行松约束。

## 验收判据汇总

- [ ] 全量 `tests/` 零失败；新增测试覆盖本任务书各条
- [ ] 每一步写入均不改变库存/IQC/预留/过账（不动账断言在 A、C、D 测试中都有）
- [ ] 钉死清单（动作全集、allowed_actions、操作目录）全部显式更新，无枚举长度冒充
- [ ] schema 仍为 24，新表并入 23→24 迁移；从真实 schema23 库升级的既有迁移测试通过
- [ ] E2E 走查记录完整，mes.shortage 开案的来源证据可见
- [ ] 未触碰范围外事项（webui、真实适配器、新导航）
