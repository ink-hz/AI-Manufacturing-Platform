# 制造导入、测试标定与能力复用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在统一制造工作台实现用户确认的工程导入、物料协同、测试标定、履历、资产复用与权威来源能力，并用隔离模拟数据走通跨项目闭环。

**Architecture:** 复用现有注册式命令与对象、SQLite事务和权限机制，分领域增量扩展。新增界面使用现有API、草稿与冲突机制；已有ERP/MES/WMS保持显式模拟状态。测试执行和管理职责分离，通过受控运行记录衔接现有质量事实。

**Tech Stack:** Python >=3.11 / FastAPI / Pydantic2 / SQLite / React19 / TypeScript / Vitest / pytest。

## Global Constraints

- Python >=3.11；沿用 FastAPI、Pydantic、SQLite、React19、TypeScript、Vite；不新增第三方运行依赖。
- 所有新写动作进入现有 WorkflowService/CommandRegistry；所有新对象进入 ObjectRegistry。沿用实时授权、只读、CSRF、CAS、操作 UUID 幂等、真实操作者审计和 private/no-store。
- 平台所有者与平台管理员默认拥有全部现有及未来项目和全部已注册业务动作；普通成员继续按项目角色、资格隔离。
- 外部 ERP/MRP/MES/WMS 和设备尚未真实接入；界面持续显示人工登记或隔离模拟来源，禁止伪造连接成功、客户批准、测试、标定写入或生产事实。
- 新记录采用增量 schema 迁移；原工单/SN/限值/协议/历史不静默改写；既有未绑定新流程的项目保持原有业务行为。
- 客户专属记录不得因复用而跨项目公开。公共资产只公开审核后的通用内容，源项目与源问题仍按原权限保护。
- 原始 PPT 与现有用户材料保留备份。89项问题明细和40站定义没有提供，不补造为真实数据；所有新增演示样本明确标为模拟。
- 工业设备控制、真实标定算法、真实企业外部系统接入和生产现场验收不由模拟流程冒充。

## Task 1: 工程导入与受控复用资产后端

**Files:** Create `src/manufacturing_platform/workflow/introduction_models.py`, `introduction.py`, `introduction_schema.py`, `tests/workflow/test_introduction.py`; modify `commands.py`, `contracts.py`, `service.py`, `store.py`, `schema.py`, `api.py`, `execution.py` and registry expectation tests only where this task requires registration/migration/gating.

**Interfaces:** Existing WorkflowService.execute, CommandContext, ObjectRegistry, require_project, DomainError, SourceRef, engineering revisions/work orders and quality evidence. Produces objects `npi`, `npi_issue`, `reusable_asset`, `asset_use`; actions `npi.open`, `npi.review`, `npi.trial`, `npi.issue`, `npi.resolve`, `npi.approve`, `asset.publish`, `asset.apply`, `asset.verify`. New model fields must be strict and publish named DTOs for UI; document exact signatures and payloads in task report.

- [ ] Write HTTP tests first covering NPI bound to same-project fixed revision, review blockers, real trial evidence, unresolved issues, explicit bulk-start gate; asset publish/apply/verify with immutable revisions, applicability and public sanitization. Use existing workflow fixture/source and test_quality scenario helpers to exercise actual commands; write before production code and record expected RED output.
- [ ] Implement typed NPI models, additive schema migration and registry readers/handlers. NPI open contains revision_id, product_family and scenario; review stores required checks and evidence; trial binds actual same-revision work order and requires real completed test evidence for approval. Approval checks reviews, issues and adopted required checks. Bind participating work orders explicitly; bulk-start checks NPI approval while trial and unbound old work orders retain existing checks.
- [ ] Implement issue lifecycle and immutable published asset revisions. Resolved issue requires actual countermeasure, verified cause and verification evidence. Asset publish requires resolved source issue and product family; generic public content is separately authored and configuration-admin approved. Applications pin asset revision and own snapshot, require applicability, and produce independent verified check records. No cross-project source details leak through relations, catalog or validation errors.
- [ ] Add `GET /reusable-assets` with bounded pagination and sanitized public entries; project-only assets remain available through existing authorized object endpoints. Public catalog requires a live authorized workflow actor and does not confer source-project access.
- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_introduction.py tests/workflow/test_a1_extensions.py tests/workflow/test_admin_full_access.py -q`; then related full workflow regression once. Record GREEN and self-review, commit only task files, write report with DTO/action examples and migration version.

## Task 2: 测试标定、原始结果与组件履历后端

**Files:** Create `workflow/laboratory_models.py`, `laboratory.py`, `laboratory_schema.py`, `tests/workflow/test_laboratory.py`; modify shared registries/store/API and existing quality integration only as required. Full directory prefix is `src/manufacturing_platform/`.

**Interfaces:** Consumes same-version engineering TestSpec, existing unit/work-order/quality execution evidence and task1 registry extensions. Produces `test_plan`, `test_run`, `calibration`, `component_link`, plus actions `test_plan.publish`, `test_run.start`, `test_run.finish`, `calibration.record`, `calibration.confirm`, `component.install`, `component.remove`, `unit.alias`.

- [ ] Write failing HTTP scenarios using real existing production/test fixtures: program or revision mismatch rejected; start captures evidence scope; completed run enters current quality path; interrupted/invalid run never passes; immutable attempts preserve failed history; stale execution cannot satisfy finish; calibration requires successful matching run and independent readback confirmation; component active uniqueness and removal history; cross-project/replay/CAS/readonly protections.
- [ ] Implement additive typed models and migration. Published plan pins revision TestSpec; mutable input cannot replace program/limits/firmware. Finish measurement validation delegates to existing quality handler, maintaining real execution, equipment, rework and release conditions. Any finish variant producing a quality fact must enforce the same current roles/qualifications as `test.record`, including before idempotent replay; delegation cannot broaden ordinary production-role permissions. Run lifecycle and verdict remain independent. Raw curves have finite numeric sampling points, units, bounded size and digest; logs bounded. Detail returns raw evidence with source; never load arbitrary filesystem paths or URLs.
- [ ] Implement calibrated parameter records, algorithm/version/run linkage and independent confirmation with matching readback parameter content. Human/manual and demo sources visible; absent confirmation remains pending. No device-control claims or quality-release side effects.
- [ ] Implement component install/remove by parent unit and explicit material/serial identity, with scoped optional lot; prohibit simultaneous active installations and preserve closure history. Expose parent relations in typed object detail without modifying inventory or prior consumption. Add `unit.alias(unit_id, customer_serial, evidence)` preserving globally unique factory SN and immutable aliases. Customer serial uniqueness is scoped to customer identity, allowing two different customers to each use `001`; reject collisions without revealing unauthorized objects. Unit detail exposes aliases only within normal project authorization. Test alias separation, cross-project collisions for the same customer, replay and history.
- [ ] Run focused new suite and existing quality/execution/trace suites, then related full workflow once; record RED/GREEN and exact DTO payloads, commit and report.

## Task 3: 权威映射、可追责辅助分析与物料业务细化

**Files:** Create `src/manufacturing_platform/workflow/authority_models.py`, `authority.py`, `authority_schema.py`, `arrival_models.py`, `arrival.py`, `arrival_schema.py`, `assistance.py`, `tests/workflow/test_authority_assistance.py`, `tests/workflow/test_arrivals.py`; source files after the first use the same `src/manufacturing_platform/workflow/` directory. Modify registry/API/store, supply query models and source adapters only as necessary.

**Interfaces:** Existing SourceRef, project grants, mock adapters, exchange receipts and object readers; new `authority_rule` object, `authority.register`, `authority.verify` actions; `arrival` observation object with `arrival.record` and `arrival.match`. Assistance is read-only project-scoped API `/projects/{project_id}/assistance?kind=introduction|materials|change|knowledge|testing|quality`, returning mode `rules`, evidence references, known blockers and explicit unknowns, never performing mutation.

- [ ] Test live authorization, CSRF/CAS/replay and immutable mapping revision history. Mapping registration does not connect a source or change existing production. Verifying requires contract evidence; actual production-connected state cannot be set by an HTTP field. Demo adapters are visibly demo.
- [ ] Implement strict scoped authority mapping by object category and system with responsible identity text and evidence. Preserve per-scope revisions and current active projection. Do not create a second inventory balance or silently switch authority for in-flight objects.
- [ ] Implement bounded read-only rule assistance from authorized records: current NPI missing checks/unresolved issues, actual material accepted/pending/rejected quantities and existing requirements, actual ECO affected objects, approved applicable assets. Each suggestion references real object IDs; zero records returns explicit no-evidence state, not invented recommendations. Source scope and rule mode are visible. Public sanitized assets may be searched; private source data cannot be fetched through suggestions. Testing drafts report actual failed measurements/run states/similar scoped records with citations and no causal/prediction claim. Quality drafts organize existing NCR/RMA/CAPA facts, registered causes/actions/verification and explicit missing fields into an8D evidence outline, without inventing facts or performing approval. Cover both modes with real HTTP positive/empty/scope/no-write tests.
- [ ] Implement actual lightweight receiving for known project responsibility: `arrival.record` accepts scanned/typed arrival number, location, package count, description and manual attributable source, without requiring an existing purchase order/material/qualified lot. Pending observation never creates stock or IQC quantities. `arrival.match` links only an actual same-project existing receipt; later correction needs explicit reason and append-only match history, preserving original relation/audit. Test unlinked state, foreign receipt refusal, replay/CAS/readonly, correction history and exact unchanged inventory/IQC/reservation tables for both actions. Arrival is a non-accounting observation, not a second WMS.
- [ ] Add clear receipt quantity state/next action presentation fields using existing accepted/rejected/pending computations; preserve partial IQC semantics and reservation authority boundaries. Materials assistance includes real pending arrival identity checks; cannot infer unknown packages have arrived without observation.
- [ ] Verify focused new tests and supply/import/authorization regressions, record commands and results, commit and report exact DTO signatures.

## Task 4: 可操作工作区、表单、曲线与关联导航

**Files:** `webui/src/workflow/types.ts`, `api.ts`, `navigationContext.ts`, `WorkflowApp.tsx`, `WorkflowDetail.tsx`, `WorkflowHome.tsx`, `StatusBadge.tsx`, `labels.ts`, `console/ConsoleShell.tsx`; create focused `IntroductionWorkspace.tsx`, `LaboratoryWorkspace.tsx`, forms/detail modules and focused component/HTTP tests. Extend existing supply/exchange workspaces for Task3, including arrival scan/typed registration, receipt matching/correction and quantity states.

**Interfaces:** Consume exact task1–3 registered DTOs and commands; use existing WorkspaceProps, ObjectChoice, Form, requestLeave/onDirty, project version and API authentication retirement. New global navigation `introduction` and `laboratory`; project context and old direct routes remain functional.

- [ ] Write failing component tests for creating NPI from fixed revision, required checks and issue lifecycle; asset adoption and verification; selecting a SN and publishing/starting/finishing a test run; aborted verdict; curve values/units; calibration pending then confirmed; authority registered versus demo/connected distinction; no hidden JSON entry or fake action buttons.
- [ ] Implement named forms for every new registered business action and typed details with source/evidence/history. Every visible action must submit a real command and refresh using mutation acknowledgement. Do not require users to type UUIDs when objects can be selected. Empty/loading/error/readonly and CAS conflict states must remain useful.
- [ ] Integrate engineering/asset and laboratory global ledgers, project workspaces and object-opening targets. Add single-unit passport sections for component history, testing and calibration; preserve draft decisions and late-response protection. Keep compact visual hierarchy and existing continuous handbook.
- [ ] Render bounded curve evidence using native accessible SVG with a numeric table; labels and units come from actual result data. Add read-only assistance panels clearly labeled rule analysis with source links and no AI execution claim.
- [ ] Run focused UI tests, `npm test`, `npm run build`, bundle check where applicable; record outputs, commit, self-review and report.

## Task 5: 全流程模拟、设计文档同步与最终集成

**Files:** Add isolated script/fixtures, `scripts/preview_manufacturing.py`, `scripts/build_preview_renderer.mjs`, `tests/workflow/test_preview_manufacturing.py` and `tests/workflow/test_oem_capabilities_flow.py`; revise `docs/manufacturing-workbench-product-design.md`, `docs/manufacturing-platform-architecture.md`; preserve source PPT and transfer Markdown; add verification report.

- [ ] Write and run actual HTTP scenario: project A issue→verified resolution→public sanitized asset→project B applicable adoption/check→NPI approval; real test run fail/interrupted→rework/pass→calibration/readback→component replacement/history. Prove unauthorized project cannot read source, admin default future projects, stale version, duplicate operation and revoked actor handled.
- [ ] Check S1–S9 progress and action hints against explicitly linked NPI current eligibility: distinguish trial engineering readiness from bulk qualification and avoid presenting an unapproved required introduction as fully qualified. Add focused integration coverage for the chosen honest presentation.
- [ ] Create explicit isolated synthetic dataset with coherent camera and robot examples and actionable current states. Do not reseed production or replace existing six projects. Provide reproducible local command and clearly mark it simulated. Provide an operable loopback-only preview using the built business bundle and exact existing Platform manufacturingMarkdown renderer (bundle preview bridge from its source with existing esbuild, no Platform edits/new dependencies). Preview uses a separately owned demo directory/manifest and clearly synthetic local admin, exact Host and write Origin/CSRF checks, no employee sessions, no reset/debug endpoints exposed, and no production paths. Serve only explicit built assets. Test startup/host/origin/CSRF/dataset isolation and real business commands. Read private preview-notes.md for existing renderer paths and prototype constraints.
- [ ] Update product positioning and authority architecture, test execution boundary, SN composition, controlled knowledge and NPI semantics. Preserve user draft source and merge only approved additions; do not convert PPT assertions into established factory capabilities.
- [ ] Run backend regression, frontend full suite/build, extended actual HTTP flow and original36 acceptance as their documented runner permits. Record unavailable environment-dependent checks honestly. Run task reviews and one final whole-branch review, fix all blocking findings, then integrate reviewed work without losing canonical uncommitted materials.
