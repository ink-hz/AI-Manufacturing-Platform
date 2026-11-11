# 工单料况分析与急料实收核对 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 计划员跨全项目找物料、看并行卡点并交给实际责任人；接收人声明本次实收用途，MC凭当前数量与实收证据核对急料解决。

**Architecture:** 在已确认的料况设计和T2/T4任务书上继续。共享平台事实分析先判定再分页，需求时间用增量事件保存；平台预留、质量与实收分开。新增实收用途作为指定接收人的类型化声明，急料结束在事务内重新核对；原生MES/SAP观察继续保留各自语义。

**Tech Stack:** Python/FastAPI/Pydantic/SQLite；React/TypeScript/Vitest；现有项目命令/CAS/幂等/审计与原生只读源。

## Global Constraints

- 用户已批准机器人OEM代工代料设计并要求继续开发；复用现有项目、工单、需求、急料、IQC/寻料和指定签收，不重复做管理CRUD。
- 每项功能有实际岗位操作和失败恢复。主页面给卡点、数量、负责人及行动；不展示原始JSON、内部UUID输入或整屏技术状态说明。
- 数量使用整数原子/Decimal和十进制字符串，按物料/货主/工单/需求lineage/单位核对。不得相加收货、合格、预留和实收里程碑，不将共享储备重复满足多条需求，不将MES原始数量当净需求。
- 搜索/工单/问题过滤在需求分页之前，完整匹配总数与返回行一致。分类不使用200行预览或首501行代替全范围；详细历史仅显式详情加载。
- 在办急料是已确认协调事实；时间风险建议独立显示。需要时间缺失为未知，工单开工时间只是明确标记的代理，不假定班次、SLA或新增承诺交期。
- 以当前有效收货/IQC/权威确认预留计算平台口径。过期、冻结、隔离、所有权冲突及当前合格不足的批次不得显示为可满足。全量分析复用批量余额，按需求/工单正确隔离，按批次缓存检查，不逐需求加载对象历史。
- 交接只有批次/工单时不能证明归属。明确`receipt_use=line_side`且带`requirement_id`的实际签收才可计作本需求线边实收；老记录默认为`unspecified`。只有指定接收人可声明/补充用途，管理员不能代签，文本“找到/已处理”不产生实收数量。
- 急料`fulfilled`必须在写事务内重新核对当前计划、合格可用预留及唯一可归属的实收；预览不能当审批令牌。多笔独立交接/多段流转不能直接相加；首期成功范围为唯一直接线边交接，或一组现有独占寻料补收证据，其他歧义明确阻断。20需/18收仍差2，签收补收2且关系核实才可完成。
- 本次不宣称SAP/MES等价、真实OEM同单IQC/WMS闭环或生产发布。已知SAP/MES样本不匹配保持未关联；原生观察不写成计划/库存/放行事实。浏览器验收由用户承担。
- 保留用户原有dirty/untracked资料及原始私有配置；在既有隔离工作树新任务分支开发，审查/验证后本地合入，不推送、不部署、不发送业务通知。

---

### Task 1: 全范围料况分析、准确卡点与需要时间

**Files:** New focused `workflow/material_analysis.py`, `workflow/material_eligibility.py`, `workflow/material_need_time.py`; modify `workflow/{material_control,material_control_models,material_control_api,supply,supply_models,commands,service,schema,store}.py` as needed; tests `tests/workflow/test_material_analysis.py`, `test_material_control.py` and relevant schema/command tests.

**Interfaces:** Extend current material-control GET with `search: str=''` (max200), `problem: Literal['all','attention','shortage','urgent','pending_iqc','unreceived','verification']='all'`, existing work_order_id/requirement_id retained. `project_view` appends optional search/problem args so old callers work. Response retains old fields and adds `scope_total`, `problem_counts`, requirement `confirmed_satisfied`, `issues`, `timing_risk`, `need_time_history_count`. Issues: `{code,title,object_kind,object_id,quantity,unit,task_id,assignee_id,assignee_name,proposed_assignee_id,proposed_assignee_name,next_action}`; next_action is `view_task|arrange_iqc|trace|expedite|view_object|confirm_time|check_allocation`, no arbitrary route. Actor-specific actions use existing policy; unknown names display待分派/负责人待核对 rather than UUID.

`material_eligibility.lot_unavailable_reason(tx,project_id,lot,now)` returns reason string orNone, covering expiry(date before business now's date), active state, existing ownership/freeze holds and authority claims exceeding current accepted quantity. Reuse in `available` and batch balances, preserve independent raw reserved/received/qualified values. `confirmed_satisfied` is capped at required and reflects valid reservation coverage, never line-side receipt.

Add `material.need_time` command `{operation_id,expected_version,requirement_id,need_at:awareISO|null,evidence}` for active project_owner/planner/supply, current confirmed requirement only. Save append-only events in schema27; null explicitly resets to work-order proxy. Current projection reads latest exact-requirement event; replan does not silently inherit it. Requirement detail exposes `need_time_events` typed history; quantity/accounting facts untouched.

- [ ] Write red tests for 51st material and work-order search beforepage/total, simultaneous IQC+short-receipt tags, current vs proposed task assignee, same-lot ambiguity, supplementary signed-receipt proof, current vs historical requirement and permission boundaries.
- [ ] Write eligibility tests for expired/frozen/held/current-quality-correction claims, shared stock across demands, exactfraction/unit/owner/workorder mismatch; align batch and single balance. Implement one complete analysis projection, query facts in batches and cache per-lot checks; never call detail/history per requirement or impose a hidden data cap.
- [ ] Add timezone, permissions, read-only, replay/CAS, replan, reset/history, fresh schema27/v26 migration tests for need-time; implement registered command and stable DTO fields.
- [ ] Run focused tests and relevant supply/readiness/execution regressions with `/private/tmp/manufacturing-contract-py311/bin/python`; record actual red/green/output. Commit owned backend files only. Report `.superpowers/sdd/material-analysis/task1-report.md` including final DTO for UI.

### Task 2: 指定接收人核对实收用途、急料按当前证据结束

**Files:** `workflow/{material_handoff_models,material_handoffs,expedite_models,expedite,commands}.py`; new `workflow/expedite_fulfillment.py`; tests `test_material_handoffs.py`, `test_expedite_fulfillment.py`, affected existing expedited lifecycle tests. Parent may implement this task while Task1 backend agent works, with nonoverlapping ownership.

**Interfaces:** ReceiveMaterialHandoff/HandoffReceipt add `receipt_use: Literal['unspecified','transfer','line_side']='unspecified'`, `requirement_id:UUID|null=None`; line_side requires a current compatible requirement, other uses must not carry a requirement. Signature quantities/location remain actual signed facts. New `material_handoff.confirm_use` command `{operation_id,expected_version,handoff_id,receipt_use:'transfer'|'line_side',requirement_id,evidence}` allows the actual receiver to add use to an existing unspecified signed receipt once. Preserve original actor/time/quantity; store scope actor/time/evidence separately. No source/inventory/quality write.

`ExpediteClosure` adds optional immutable `fulfillment_proof`; legacy closures remain proof absent. `MaterialExpedite` detail adds current `fulfillment_check` via shared evaluator; no new host route. Check DTO includes `{can_fulfill,evaluated_at,project_version,requirement_id,current_requirement_id,required,qualified,usable_reserved,line_received,remaining_to_receive,unit,blocking_reasons,evidence_refs}`. Unknown line attribution is null, not zero. Successful close stores the exact versioned proof. `false_alarm/superseded` remain coordination outcomes and do not imply quantity fulfilment.

- [ ] Write failing HTTP tests: text-onlyfulfilled,20/18/free-text-resolved/IQC-only/unconfirmed reservation, otherlineage/lot/unit/sharedhandoff/multileg allblocked; direct actor-specific receipt_use declaration accepted, admin proxy and incompatible/current-scope claims rejected.
- [ ] Implement new typed receive/use scope and immutable attestation, exact current-lineage evaluator. Positive mode: all candidate handoffs belong to one directly signed line-side event, or one exclusively linked trace root+signed supplements group; prove same material/owner/unit/workorder and actual receiver, don't duplicate candidate joins or cross-requirement credits. Independent extra legs/unknown scopes block with concrete reasons. Require qualified usable authority-backed reserve for the same credited lot; use current eligibility and do not count only a historical verification state.
- [ ] Enforce evaluator in existing close handler after ordinary authorization/replay/CAS, store proof snapshot onfulfilled. Test stale preview then correction/freeze/replan/revoke; exact replay remains savedproof, changedpayload conflicts, failures create no closure/operation receipt. Test legacy proof absence preserved.
- [ ] Run related handoff/task/expedite regressions; report `.superpowers/sdd/material-analysis/task2-report.md`, commit only owned files, coordinate central commands edit after Task1 commit.

### Task 3: 料况页直接找料、办理卡点及核对结束

**Files:** `webui/src/workflow/materialControl/{MaterialControlWorkspace,MaterialTaskOpen,ExpeditePanel,types,api}.ts(x)`; new focused need-time editor and issue presentation; handoff receipt form in existing workspace/details; command types and relevant navigation tests.

**Interfaces:** Add optional filter object as fifth `materialProject(id,limit,offset,signal?,filters?)` argument, preserve old calls. Extend MaterialViewContext with problem(defaultattention) while tolerating older contexts. Need-time uses Task1 command and requirementdetail history. Typed receipt/use and fulfilment check use Task2 exact contracts, current requirements chosen by human material/workorder labels. Keep `onMaterialChanged` in-place acknowledgement and all established draft owners/reset boundaries.

- [ ] Add failing tests for server-side query/filter beforepage, independent workorder picker options, issuechips/current and proposed responsible names, simultaneous object-specific actions, need-time proxy/manual/history and stale draft protection.
- [ ] Replace本页筛选 with全项目 search and problem filter, reset offset through guarded transitions; show exact卡点 and actionable buttons. Open existing tasks or prefill correct receipt/handoff when arranging IQC/trace; do not ask for raw IDs. Return context/drafts/paging preserved. Display current confirmed-plan quantity basis and keep nativeMES component observations separate.
- [ ] Add实际收料用途+需求选择 to receive and retrospective用途确认 for actual receiver; show transfer/line-side/unspecified accurately. Add急料核对面板: stage quantities separately, concrete blockers, disablefulfilled when preview blocked, still rely on serverreevaluation; oldproofless closures labelledhistorical. Successful mutations stay at source owner and acknowledge version even after selection changes.
- [ ] Run focused component/App integration tests then normal Vitest excluding dedicated acceptanceNavigationHttp harness, `npm run test:bundle`; retain guarded navigation regressions from previous delivery. Report `.superpowers/sdd/material-analysis/task3-report.md`, commit owned sources; dist remainsignored.

### Task 4: 流程验证与本地主线交付

**Files:** meaningful HTTP workflow regression covering samecase lifecycle, `docs/verification/material-analysis-2026-11-12.md`, taskbook status/index. PF changes only if a reviewed new host route is truly necessary; current design uses existing routes.

- [ ] Verify controlled platform journey through authorized APIs: confirmedneed→急料→IQC/task→有效分配→交出20/实收18→寻料找到2仍不完成→指定人补签2+独占补收关联→核对结束；corrected/held/shared/oldtime versions remain blocked. No direct DB success fabrication.
- [ ] Rerun dedicated E30 with real loopback HTTP and current PF source. Separately rerun existing opt-in nativeMES/SAP test reads through actual host with isolated private config copies when new source-facing changes justify it; never call synthetic platform facts real OEM/MES/IQC/WMS physical closure. Source identity mismatch remains unresolved.
- [ ] Task reviews + final wholebranch review, fix actionable findings, guarded localFF and original-root relatedtests/bundle, compare generated artifacts and preserved user file hashes. Record delivered behaviors and remaining source contract dependencies without claiming entire programcomplete.
