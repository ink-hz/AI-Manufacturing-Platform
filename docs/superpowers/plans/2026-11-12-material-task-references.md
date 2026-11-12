# M2物料任务引用实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在没有平台需求/正式收货时也能引用已有观察派人核实；已有准确收货直接安排IQC，不要求重录一套账。

**Architecture:** 扩展现有material_tasks、保留原IQC/trace规则；严格引用由服务器从持久对象解析，固定初始证据、另给当前状态。数据库v28迁移、生命周期、页面、宿主HTTP依次交付与独立审查。

**Tech Stack:** Python3.11/Pydantic/SQLite/FastAPI、React19/TypeScript/Vitest；现有PF宿主精确允许清单与回环HTTP。

## Global Constraints

- 生产MES/WMS、SAP/MRP只读；本轮不访问实际源，不执行源业务写入、MRP、打印或回写。
- 观察不等于正式收货、检验、预留或实收；核实任务只写协同/历史/关联，不隐式创建需求、承诺、批次、收货、IQC、交接、exchange或集成事实。
- 新核实任务可无requirement_id；旧IQC/trace及历史、补收组保持可读可办。IQC从准确收货推导需求，trace仍要求需求与交接。
- 服务器按当前项目持久对象解析引用，不信客户端的来源、环境、数量、URL或对象快照。source_receipt必须已有接受的准确投影，当前事实的mock身份保留。
- SourceRef写入契约及T2来源/环境/角色语义不放宽，命名空间/环境按已保存依据，未知仍unknown。
- 初始引用固定；刷新快照不新建同范围在办任务；绑定替换不暗改旧任务。稳定去重范围与快照证据版本分开。
- 核实结论使用identity_verified/unable_to_verify/incorrect_observation/superseded；旧IQC/trace仍用原结论和真实数量proof。找到量、包裹数、原生已提料不作为IQC/实收完成依据。
- IQC关联维持现有lineage/工单/物料/货主/单位/精度证明；核实需求关联只是上下文，不分配数量；不实现无证据的跨工单共享检验。
- v27→v28保持FK开启与事务原子性，保留seq/ID、原JSON/source/closure/历史/补收证据及sqlite_sequence高水位，foreign_key_check通过才推进版本。
- 复用现有料况、项目任务列表、事项与详情，无新一级导航；项目/用户/API/引用/操作代次隔离、CAS、幂等、目录有效性及撤权不退化。
- M6事项每项目截断、原生生产收货/IQC准入、M1完整料况内交接、SAP mock不在本轮声称完成。
- 本地快进交付，保留用户改动与工作树；不推送/部署或执行生产平台数据库迁移。浏览器/现场验收由用户另行执行。

## 基线与执行

依据[已确认设计](../specs/2026-11-12-material-task-references-design.md)、[M2任务书](../../taskbooks/robot-oem/03-iqc-receipt-and-results.md)。使用已授权开发流程连续执行，不另等一次“继续”。

MF工作树`/Users/neo/.codex/worktrees/4ce0/AI-Manufacturing-Platform`，分支`codex/oem-task-references-20261112`，基线`618abf4`；rootmain同基线，原777文件预映像`/private/tmp/oem-task-references-baseline-20261112.json`。基线material_tasks＋arrivals37项通过（12.05秒）。PF复用`/Users/neo/.codex/worktrees/robot-oem-material-host-20261111/AI-Agent-Platform`，基线`70bf974d`，Task4开始前建立独立功能分支；不切换PF用户原检出。生产只读AGENTS传递到所有子任务。

Python：`PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest ...`。UI在`webui/`。宿主使用`/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python`。SDD报告保留`.superpowers/sdd/material-task-references/`，不强制提交被忽略的报告。

## 共享接口

Create `workflow/material_task_reference_models.py`：严格、带discriminator的输入和只读投影，不复用可写SourceRef作为可信声明。

```python
class ArrivalTaskReference(StrictModel):
    kind: Literal['arrival']
    id: UUID
    version: int = Field(strict=True, ge=1)
class MesComponentTaskReference(StrictModel):
    kind: Literal['mes_component']
    binding_id: UUID
    snapshot_id: UUID
    component_key: str = Field(min_length=1, max_length=128)
class ReceiptTaskReference(StrictModel):
    kind: Literal['receipt']
    id: UUID
class SourceReceiptTaskReference(StrictModel):
    kind: Literal['source_receipt']
    source_key: SourceKey
TaskReference = Annotated[ArrivalTaskReference | MesComponentTaskReference |
    ReceiptTaskReference | SourceReceiptTaskReference, Field(discriminator='kind')]
```

`TaskReferenceEvidence`返回`reference:TaskReference`、`scope_key:str`、`title:str`、`origin`、`environment`、`system/source_type/external_id/version/namespace/occurred_at/collected_at`、可空`work_order_id/material_id/material_lot_id/receipt_id/unit`；字段按真实来源填，未知为null或unknown。mode/API标签不能自行证明原生，沿用T2规范身份/可信投影校验。身份只含可向当前授权用户展示的字段，不复制原始记录/签名/配置。`ResolvedTaskReference`额外给`requirement_id:UUID|None`及支持的任务种类，供写侧使用。

对外函数放`workflow/material_task_references.py`，需要时将纯查询列表拆到`material_task_reference_query.py`：

```python
def resolve_reference(tx, project_id, reference: TaskReference, *, require_current=True) -> ResolvedTaskReference: ...
def reference_status(tx, project_id, evidence: TaskReferenceEvidence):
    # returns (is_current:bool, current_reference:TaskReference|None, issue:str|None)
    ...
def reference_page(service, actor, project_id, *, task_kind='verify', kind='all',
                   work_order_id=None, requirement_id=None, search='', limit=50, offset=0): ...
```

`reference_page`返回project_id/project_version/read_at/task_kind/items/total/limit/offset；每项为reference、evidence、existing_task_id、can_open。task_kind只接受verify/iqc；类型all/arrival/mes_component/receipt/source_receipt。先授权和业务筛选再分页，收货别名按实际receipt_id去重，优先提供已验证源引用；重复读取不触发采集/准入。分页工单与需求参数不存在/外项目为404。核实的到场观察无工单身份时明确待关联；MES按工单筛选；IQC按现有可证明范围筛选。

`OpenMaterialTask`: requirement_id可空默认None，task_kind增加verify，reference可空；旧receipt/handoff字段保留。新引用不能和legacy对象字段混填。`CloseMaterialTask`的outcome并集增加核实结论，另加`resolved_reference:TaskReference|None`。IQC/trace拒绝核实结论与resolved_reference；verify拒绝旧数量完成结论、handoff_ids和找到量。TaskHistory/MaterialTask读模型补引用、闭包、context_requirement_ids、reference_pinned/reference_current/current_reference/reference_issue，旧JSON缺项用明确兼容默认。

### Task 1: FK安全迁移、引用解析与分页发现

**Files:** Create `workflow/material_task_reference_models.py`、`material_task_references.py`、`material_task_reference_query.py`（列表职责需要时）、`material_task_reference_migration.py`；Modify `material_task_models.py`、`material_task_schema.py`、`schema.py`、`store.py`、`material_task_reader.py`、`material_control_api.py`；Create `tests/workflow/test_material_task_references.py`、`test_material_task_reference_migration.py`。更新现有测试中断言“当前schema=27”的位置为导入SCHEMA_VERSION，保留真正的旧版本测试设置。

**Produces:** 上述完整引用接口/DTO、GET新路由、v28可读存储；本任务不实现新verify写生命周期，旧请求行为继续通过。

- [ ] **Step 1: RED测试。** 两个隔离项目：实际arrival.record、FakeMes绑定快照、已有收货/MockRig已接受投影；解析引用需准确项目/绑定/快照/组件/源版本/哈希和目标。未投影不能触发pull；错误快照/跨项目/不存在拒绝。51+引用先过滤/计数再分页，迭代查询前后iterdump一致。

```python
def test_arrival_reference_requires_no_requirement_or_receipt(workflow):
    from .conftest import BASE
    from .test_arrivals import fields, stock
    p = workflow.create_project(mode='oem')
    arrival = workflow.command(p['id'], 'arrival.record', **fields(workflow))['object_id']
    before = stock(workflow)
    response = workflow.client().get(f"{BASE}/projects/{p['id']}/material-task-references",
                                    params={'task_kind':'verify','kind':'arrival'})
    assert response.status_code == 200
    item = response.json()['items'][0]
    assert item['reference'] == {'kind':'arrival','id':arrival,'version':1}
    assert item['evidence']['receipt_id'] is None
    assert stock(workflow) == before
```

- [ ] **Step 2: 跑新文件观察RED**：上述Python执行`test_material_task_references.py test_material_task_reference_migration.py -q --tb=short`。先核对真实harness接口，避免用假字段当预期失败。
- [ ] **Step 3: 实现。** 历史v25初始化用明确legacy schema；fresh v28用新表。v27迁移在FK开启的当前事务创建替代父/子表、复制完整行、按正确顺序删除/重命名/建索引。新增reference_json/reference_key，verify允许空需求，新增material_task_requirements并回填旧真实主需求；旧payload/closure/source字节不改。保留sqlite_sequence高水位，失败完整回滚，重开幂等。已具新结构但测试降级版本号的存储仍须正确校验/初始化，不伪造历史依据。
- [ ] **Step 4: GREEN和迁移回归。** 新测试＋37基线；运行`test_native_materials.py`、`test_material_analysis.py`、`test_issue_mark_migration.py`和`integrations/{test_core_compatibility,test_profile_migration,test_operation_boundary}.py`。覆盖旧IQC/trace所有状态、转交、历史、补收外键、故意失败回滚、高水位及后续插入。保存固定证据与当前状态分离，不把旧任务当前记录倒称为初始快照。
- [ ] **Step 5: Commit精确文件**，报告RED/GREEN、迁移策略、接口及范围限制，进入独立spec/quality审查。

### Task 2: 核实与直接引用IQC的完整生命周期

**Files:** Modify `workflow/material_tasks.py`、`material_task_models.py`、`material_task_reader.py`、`material_control_api.py`、`service.py`；Create `workflow/material_verification.py`（结论/当前引用职责）；Create `tests/workflow/test_material_verification.py`；Modify `test_material_tasks.py`及`test_material_task_references.py`。

**Consumes:** Task1 resolver/schema/query；Produces verify open/accept/progress/reassign/close/cancel，source_ref IQC与稳定去重，context links/当前引用信息。

- [ ] **Step 1: RED业务流程。** 在空需求项目中记录观察→open verify→本人接手→反馈→identity_verified或有原因结论。每步业务表快照不变；source_ref IQC推导准确需求、重复提醒复用原任务且不改责任人；无准确收货只可核实。

```python
task = workflow.command(pid, 'material_task.open', task_kind='verify',
    reference={'kind':'arrival','id':arrival,'version':1},
    assignee_id=str(USERS['warehouse']), note='核实标签与暂存位置')['object_id']
workflow.command(pid, 'material_task.accept', actor_name='warehouse', task_id=task)
workflow.command(pid, 'material_task.close', actor_name='warehouse', task_id=task,
    outcome='identity_verified', evidence='已核对实物标签和当前观察记录')
```

先从真实harness建立pid/arrival和仓库授权，不用SQL造成功事实。增加：身份不足不能IQC；未接手/撤权/只读/目录失效/CAS/幂等；12合格8待检不能close，12合格8拒收可close本次检验；trace补收校验保持。
- [ ] **Step 2: 观察RED后实现显式三种kind分派。** verify资格为当前项目供料/项目负责人/仓库/生产/质量成员；IQC仍quality＋inspection；老trace保持。复用既有授权/subject检查。open同时校验上下文，保存固定服务器引用；IQC缺主需求时从准确收货推导。reference_key稳定范围查到在办任务即返回原ID，不偷换责任人，兼容需求链接有历史；旧duplicate409测试改为验证复用、历史与无业务副作用。
- [ ] **Step 3: 核实close。** pending不可完成；当前实际负责人/有效授权；结论与必填依据。identity_verified重核当前引用；陈旧时必须明确resolved_reference，同稳定范围方可更新完成依据；替换绑定不得跨过去。arrival→receipt只允许已存在且当前匹配的准确收货；native组件不得仅同物料转receipt。unable/incorrect/superseded留原因，材料问题不消失。verify拒绝找到量/补签/检验数量，`material_task.verify`不用于verify类型，summary不提供多余阶段动作。
- [ ] **Step 4: GREEN。** 新生命周期/引用/迁移测试＋现有`test_material_tasks.py`、`test_expedite_tasks.py`、`test_material_analysis.py`、`test_material_provenance.py`、`test_expedite_fulfillment.py`、`test_material_resolution_journey.py`、`test_arrivals.py`；重启及旧任务读取、别名去重、历史需求兼容、多人需求关联不分配数量。M6集合不在本任务改写，明确仍有限制。
- [ ] **Step 5: Commit精确生产/测试文件**，报告实际结果及source_ref当前mock/原生尚未准入边界，独立审查。

### Task 3: 空需求也能就地派核实，岗位详情办理

**Files:** Create `webui/src/workflow/materialControl/MaterialReferenceOpen.tsx`、`MaterialReferencePicker.tsx`、`MaterialReferenceContext.tsx`、`VerificationFields.tsx`，按职责保持小文件；Modify `MaterialControlWorkspace.tsx`、`MaterialTaskOpen.tsx`、`MesOrderMaterials.tsx`、`MaterialTaskPanel.tsx`、`MaterialTaskList.tsx`、`MaterialTaskContext.tsx`、`types.ts`、`api.ts`和`workflow/types.ts`。到场观察例外表单可新增独立`ArrivalObservationForm.tsx`，复用原arrival.record，不强迫输入技术源键/版本。测试新组件与实际WorkflowApp集成、已有草稿/来源标签。

**Consumes:** GET references及Task2命令/详情；TypeScript字段与Python JSON逐字对应。sourceReceipts保留mock/unknown，task.source的manual协同身份不遮盖reference的真实身份。

- [ ] **Step 1: 写真实组件RED。** 料况无requirements但有arrival/native ref可分派；原缺收货提示有“安排核实”实际入口；MES组件行预填引用；单据来源已有时可IQC而不填供应承诺/收货；reference列表分页和搜索，读取失败不退回假成功。
- [ ] **Step 2: 实现入口与引用选择。** 顶层和需求内均可打开同一composer，原筛选/页码/选择/草稿保留。没有观察时可就地记录实际包裹，自动元数据归责，记录后可选；不把native组件称到货。server返回已有task时打开同一对象，不重复创建。新form与源引用查询/提交绑定项目/actor/API/版本/代次，保存ACK用既有onMaterialChanged所有权，不清新草稿。
- [ ] **Step 3: 岗位详情。** 在原TaskPanel显示固定引用、当前版本及变化原因；无requirement/receipt不无限显示加载或调用缺ID。verify显示typed结论与依据，不显示IQC/查料数量；陈旧identity_verified需显式采用当前同范围引用，旧初始证据保留。有准确收货且当前人有协调权限可就地安排IQC。原转交/接手/进展、IQC部分结果、trace补收不退化。
- [ ] **Step 4: GREEN。** 组件＋实际WorkflowApp空需求/项目与用户/API切换/旧响应/撤权/保存导航/草稿覆盖测试。最后普通`npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx`及`npm run test:bundle`各执行一次；专用HTTP交Task4。旧API缺refs方法/模块不可用有明确失败与保留草稿，不能要求伪造账。
- [ ] **Step 5: Commit精确UI/测试文件**，报告RED/GREEN与实际可见行为；独立审查，不主动浏览器验收。

### Task 4: 精确宿主接入与完整受控HTTP流程

**Files MF:** `tests/workflow/scenarios/{__init__.py,exceptions.py}`、新`tests/workflow/scenarios/material_task_references.py`（完整场景）以及现有UI HTTP harness按需拆小文件；`tests/workflow/test_acceptance.py`；`webui/src/workflow/acceptanceNavigationHttp.test.tsx`及专用用例定义（先定位现有E30组织，不复制整套harness）。

**Files PF:** `backend/app/manufacturing_paths.py`、`backend/tests/test_manufacturing_material_routes.py`，必要的旧模块桥接行为只改制造宿主相关文件。

- [ ] **Step 1: PF隔离与RED。** 在既有host worktree从70bf974d开任务分支；检查根AGENTS，传递生产源只读。新GET路由缺精确允许项时，宿主受权/拒绝/旧版不可用矩阵先失败。只添加`GET /projects/{project_id}/material-task-references`，不开放宽前缀/源代理/写权限。
- [ ] **Step 2: 实现精确接入并GREEN。** 当前用户、项目作用域、管理只读/旧模块与禁用情形验证；宿主与MF分别提交，PF用户原checkout保留。
- [ ] **Step 3: 新E33完整闭环。** 在隔离数据库和真实宿主回环HTTP＋jsdom里建立空需求OEM项目的到场观察（使用实际命令）、MC派核实→仓库从事项接手→反馈→typed核实结论；同一对象/责任/历史可读且业务数量表不变。另验证已保存FakeMes组件引用不生成需求、已准入明确mock收货可直接派IQC，未准入/跨项目/错关联失败不造账。新case扩展原registry范围但不改旧case语义。
- [ ] **Step 4: 最终相关回归。** 新E33及原E30使用现有真实PF宿主、受信测试身份、源配置清空/合成数据；不能以SQL伪造成功。后端任务/迁移/引用/原料况与IQC/trace全部相关文件、普通UI和bundle已有清洁结果后，只有新变更/具体风险才重复。保留首次失败与修复后独立结果。
- [ ] **Step 5: Commit与review。** 两仓库精确文件提交及独立审查，报告所有命令、版本、场景范围与未验生产/浏览器部分。

## 最终交付

- [ ] 四项spec/quality审查清洁；整分支独立Astra审查（包含MF与PF各自diff），有问题先统一修正和复审。
- [ ] 更新M2/T3任务书与验证记录，明确核实可用、准入对象可直接引用、原生生产IQC及无证据跨工单共享仍待接续。
- [ ] 校验MF原目录777预映像、新增路径冲突及用户三项改动；PF干净master工作树保留原用户checkout；分别本地快进。
- [ ] 原目录相关回归、构建和新旧专用HTTP场景通过，产物一致、无未计划代码变化；文档补记，保留工作树，不推送或部署。
