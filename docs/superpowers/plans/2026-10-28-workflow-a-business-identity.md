# Workflow A Business Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a trusted, persistent, isolated workflow API for project members, demand/order obligations and fixed workorders without weakening legacy access.

**Architecture:** Add a versioned workflow router beside the unchanged legacy router; host authenticates identity, domain checks live grants. Normalize the new domain in its own SQLite and use a durable exchange outbox for later external actions.

**Tech Stack:** Existing Python >=3.11, FastAPI >=0.115,<1, Pydantic >=2,<3, sqlite3, pytest/httpx; React19/TypeScript/Vitest host contracts.

## Global Constraints

- “保留现有库、旧项目、资料包/固定修订、独立交接与准备记录、审计及手册。”
- “权限按对象、项目范围、业务动作和数据源在服务端校验。”
- “平台管理员身份本身不伪造这类批准。”
- “测试与演示使用独立数据库/数据目录、独立身份夹具和明确的 mock 连接配置”。
- All definitions in [technical design](../specs/2026-10-28-manufacturing-workflow-technical-design.md) are binding. No new dependency unless existing tools cannot satisfy a concrete requirement.
- MF `/Users/neo/Developer/work/AI-Manufacturing-Platform/.worktrees/full-workflow`; PF `/Users/neo/Developer/work/AI-Agent-Platform/.worktrees/full-workflow`. Run all commands in their named repository. Commit only named files; never add node_modules symlink or runtime datasets.
- User authorized continuous A→B→C→D. A completion is not whole workflow completion. No browser automation or production mutations.

---

## Task A1: Versioned access boundary, isolated store and command transaction

**Files**
- Create MF `src/manufacturing_platform/workflow/{__init__.py,api.py,contracts.py,schema.py,store.py,authorization.py,service.py,commands.py,queries.py}`.
- Modify MF `src/manufacturing_platform/__init__.py` (export WORKFLOW_API_VERSION/build_workflow_router only; retain old build_router).
- Create MF `tests/workflow/{__init__.py,conftest.py,test_identity_store.py,test_contracts.py}`.
- Modify PF `backend/app/{manufacturing.py,manufacturing_paths.py}`, `backend/app/control_plane/{authorization.py,routes_auth.py}`; keep existing legacy callback unchanged.
- Create PF `backend/tests/test_manufacturing_workflow_bridge.py`; modify `backend/tests/test_manufacturing_bridge.py`, `backend/tests/test_r1_authorization.py` only for intentional shell policy assertions.
- Modify PF `webui/src/{manufacturingApi.ts,pages/ManufacturingPage.tsx,platform/PlatformSidebar.tsx}` and tests `webui/src/{pages/ManufacturingPage.test.tsx,platform/ManufacturingNavigation.test.tsx,App.manufacturing.test.tsx}`.

**Interfaces**
- Produces exact WORKFLOW_API_VERSION=1 / build_workflow_router / Actor / ProjectCreate / CommandBase / CommandResult / WorkflowStore.transaction / WorkflowService.execute/create_project/detail/objects/object_detail/dashboard from design.
- Adds `resolve_subject(user_id:UUID)->bool` trusted callback to build_workflow_router; required in host protocol and supplied by test fixture in standalone tests; never permit grants with no validation. PF implements lookup of active control user through existing auth/control user repository. This is lookup, not an alternative session system.
- `GrantChange` and `GrantView` live in contracts.py. `DomainError(code,status,message,fields,blocking_reasons)` maps public errors. `SourceRef`, `Quantity`, `Unit`, `ObjectKind`, `ObjectSummary`, `ObjectPage`, typed `ObjectDetail`, `ProjectDetail`, `Dashboard` are established here with forward module registration, not unrestricted JSON.
- Test fixture `WorkflowHarness` in tests/workflow/conftest.py: `.client(actor_name='owner')` returns TestClient with trusted injected identity and CSRF verification; `.create_project(**overrides)` uses authorized POST; `.grant(project_id,actor_name,roles,qualifications=())` uses authorized PUT; `.command(project_id,action,**fields)` fetches version then POST with fresh UUID; `.reopen()` closes/rebuilds app over same files; `.db()` returns read-only SQLite connection for assertions. `.paths` contains distinct legacy/domain/authority paths. Synthetic user IDs are fixed UUIDs per owner/engineering/planner/supply/production/quality/warehouse/outsider; no production identity hook.

- [ ] Write tests that create project/grant via API, reject unknown subject grant, verify member new access and legacy403, verify unrelated project404 and revocation, unauthorized body parse/I/O ordering, viewer write403 despite grant, hard-stale503, no-auth401, no cached permissions, unknown route/method no SPA, invalid config does not touch old files. Include byte-hash snapshot of existing legacy DB before/after.

```python
def test_member_domain_access_does_not_expose_legacy(workflow):
    p = workflow.create_project(name='Camera', quantity='100')
    workflow.grant(p['id'], 'planner', ['planner'])
    c = workflow.client('planner')
    assert c.get('/api/v1/manufacturing/workflow/access').json()['workflow_access'] is True
    assert c.get('/api/v1/manufacturing/projects').status_code == 403
    assert c.get('/api/v1/manufacturing/workflow/projects').json()['items'][0]['id'] == p['id']
    workflow.grant(p['id'], 'planner', [], active=False)
    assert c.get(f"/api/v1/manufacturing/workflow/projects/{p['id']}").status_code == 404
```

- [ ] Run MF `python -m pytest tests/workflow/test_identity_store.py tests/workflow/test_contracts.py -q`; initial failure must be missing workflow exports/behavior, not dependencies.
- [ ] Implement schema_version + dataset metadata validation, explicit path checks, SQLite FK/WAL/busy_timeout, lazy first authorized access initialization, BEGIN IMMEDIATE transaction helper; central CAS/idempotency/audit transaction. `operations` unique(dataset,actor_id,operation_id) must cover project creation and grant changes too. Save canonical request hash; exact duplicate returns original result under current authorization; changed payload conflicts. Read/write errors do not disclose paths or SQL. Configuration admin can configure grants but gets no quality action implicitly.
- [ ] Implement new router and PF exact allowlists, new unavailable handler and old-release feature detection. Intentionally absent config/old library returns200 legacy-only Bootstrap with workflow_available:false and dataset:null; configured storage failures503. Test both source versions, both enabled/disabled states, and valid legacy assets on legacy-only bootstrap. Compose new router first. Implement `authorize_workflow_identity` from AuthContext; `read_only = context.hard_stale_read_only or context.role == Role.MANAGEMENT_VIEWER`. Preserve old callback unchanged. New /assets requires exact name and release. Split manufacturing shell decorators from shared ai_engineering_shell in routes_auth.py: manufacturing requires trusted login, organization/ai-engineering retain manager guard. Extend CSP source in routes_auth.py to explicit workflow/assets directory. Add new bootstrap optional mount property and conditional new asset URL; fallback to old probe only on404. PF sidebar uses successful access probe, never frontend role.
- [ ] Write/run PF real middleware tests using FakeAuth cookie+Origin+CSRF: member scoped request200, no cookie401, forged header ignored, no-grant metadata denied, original legacy CRUD403, viewer mutation403, hard stale503, inactive subject denied, unknown paths private, preview prefix, old release still works, unavailable new feature leaves old release working. Run `python -m pytest backend/tests/test_manufacturing_workflow_bridge.py backend/tests/test_manufacturing_bridge.py backend/tests/test_r1_authorization.py -q` with the existing backend environment (from PF root, PYTHONPATH=backend if required). Run PF `npm --prefix webui test -- src/pages/ManufacturingPage.test.tsx src/platform/ManufacturingNavigation.test.tsx src/App.manufacturing.test.tsx`; expect all relevant tests pass.
- [ ] Run MF new tests again. Commit exact MF workflow/test/export files as `feat: add isolated workflow identity and store`; commit exact PF files as `feat: host scoped manufacturing workflow protocol`. Record commit IDs and reviewer findings in `.superpowers/sdd/`.

## Task A2: Demand review, formal orders and quantity obligations

**Files**
- Create MF `src/manufacturing_platform/workflow/{order_models.py,orders.py}` and `tests/workflow/test_orders.py`.
- Modify MF `workflow/{schema.py,commands.py,service.py,queries.py}` for explicit domain registration.

**Interfaces**
- Consumes Actor, SourceRef, Quantity, CommandContext and central CAS transaction.
- Produces strict action classes for demand.record/review, order.register/change/resolve_change/allocate; `orders.dispatch(tx,context,command)->MutationResult`; order line/detail queries and immutable commitment change models.
- ProjectDetail exposes `{id,version,contract,stages,summary}`; summary includes original/current order quantity,allocated,produced_good,shipped,signed,accepted,remaining_to_ship,remaining_to_accept. Unavailable future evidence remains zero/pending, never successful defaults.

- [ ] Write tests E01/E02/E25 with a forecast that cannot create a formal production obligation; four independent reviews; same external order id deduplicated by source; quantities/units/negative/precision checks; modification with existing allocation creates pending change and retains original promise; cannot shrink below delivered. Use workorder registration from A3 for final allocation integration test; start with direct creation of minimal work_order fixture row only for isolated SQL constraint test, then replace with public API in A3. No acceptance fixture may use that internal row helper.

```python
def test_forecast_cannot_become_order_without_firm_source(workflow):
    p = workflow.create_project()
    demand = workflow.command(p['id'], 'demand.record', kind='forecast', product='camera',
        quantity='100', unit='ea', due_date='2026-12-01', source=workflow.source('forecast-1'))
    response = workflow.command(p['id'], 'order.register', demand_id=demand['object_id'],
        quantity='100', unit='ea', due_date='2026-12-01', source=workflow.source('order-1'), expected_status=409)
    assert response['code'] == 'PRECONDITION_FAILED'
```

- [ ] Add harness `.source(external_id,system='erp',version=1)` returning complete manual SourceRef with fixed business clock; `.command(...expected_status=200)` asserts exact HTTP code and returns JSON. Run `python -m pytest tests/workflow/test_orders.py -q`, see failure before implementation.
- [ ] Implement normalized demand/review/order/commitment/allocation tables and actions. Formal order may reference a new firm demand linked to prior inquiry/forecast; add `supersedes_demand_id` optional to demand.record for that provenance. Four decision dimensions must individually approve. Change impact enumerates all allocated WO, supply commitment, WIP and shipment scopes; unresolved obligations block approval/cancellation. Concurrent allocations use the same transaction and sum both sides. Store original promises once; append subsequent change revisions.
- [ ] Run tests including identical UUID replay, changed-content409, concurrent CAS one success/one conflict, source external id collision across projects denied rather than linked. Commit files with `feat: model reviewed orders and fulfillment allocations`.

## Task A3: Fixed engineering, workorders and honest readiness

**Files**
- Create MF `src/manufacturing_platform/workflow/{engineering_models.py,engineering.py,readiness.py}` and `tests/workflow/test_engineering_readiness.py`.
- Modify MF workflow schema/commands/service/queries, and existing `collaboration_models.py` only if a reusable pure validator needs export; do not change old behavior.

**Interfaces**
- Produces engineering.revision/handoff/customer_approval, work_order.register, readiness.record actions.
- `readiness.evaluate(tx,project_id,work_order_id,mode,now)->ReadinessResult(ready,checks[],input_versions)`; check={kind,required,status,reason,evidence_ids}. B extends evidence sources without changing signature. `engineering.fixed_revision(tx,project_id,revision_id)->EngineeringRevision` immutable DTO.
- EngineeringRevision holds typed PackageItem[] by reuse of existing collaboration model plus fixed route steps, firmware, test specification. TestSpec = `{version,program_version,measurements:[{name,unit,lower,upper}]}`. WorkOrder holds revision_id,quantity/unit,purpose,trial_quantity,source,planned dates; add explicit `trial_quantity` to registration with `0 < trial_quantity <= quantity` when first article required.

- [ ] Write E03/E11/E12/E13 readiness unit tests and order allocation integration using API-created workorders. Snapshot old revision, register new revision, ensure old WO unchanged. Incorrect handoff retains rejected receipt and never becomes verified; correct revision resolves. Planned start outside equipment valid_until blocks both trial/bulk; customer unknown blocks required gate. Trial ready does not depend on successful first article; bulk does. Until B reservations exist material check honestly blocked.

```python
def test_revision_snapshot_survives_new_current_revision(workflow):
    p, order, wo, rev1 = workflow.order_workorder(quantity='5')
    rev2 = workflow.revision(p['id'], internal_revision='M2')
    read = workflow.object(p['id'], 'work_order', wo['id'])
    assert read['revision_id'] == rev1['id']
    assert rev2['id'] != rev1['id']
```

- [ ] Define harness `.revision`, `.order_workorder` and `.object` as public API sequences, including four reviews, package acknowledgement and required grants. Run `python -m pytest tests/workflow/test_engineering_readiness.py tests/workflow/test_orders.py -q`, see relevant failures.
- [ ] Implement immutable engineering revisions and normalized item/handoff/readiness evidence; reuse PackageItem and existing strict calendar/instant validation without invoking old ProjectRepository. Explicit new fixed_revision DTO prevents old manual phase/status composition from defining new readiness. Store source, evidence and received revision independently; no direct replace-bound revision action. Workorder quantity joins order allocation; version/material/customer/first_article checks are derived; only equipment and people evidence editable by qualified role.
- [ ] Run `python -m pytest tests/workflow tests/test_readiness_lifecycle.py tests/test_readiness_bindings.py tests/test_collaboration_integrity.py -q`; expect pass, including unchanged legacy control behavior. Commit `feat: bind workflow workorders to fixed engineering evidence`.

## Task A4: Minimal business UI and handoff contract gate

**Files**
- Create MF `webui/src/workflow/{types.ts,api.ts,WorkflowHome.tsx,WorkflowProjects.tsx,OrdersWorkspace.tsx,WorkflowDetail.tsx,forms/OrdersForms.tsx,forms/EngineeringForms.tsx,api.test.ts,orders.test.tsx,workflow.css}`.
- Modify MF `webui/src/{types.ts,App.tsx,console/ConsoleShell.tsx}` and `webui/src/App.test.tsx`.

**Interfaces**
- `createWorkflowApi(options,onAuthError)` exports bootstrap/projects/project/createProject/members/grant/objects/object/command/dashboard/exchanges/trace/handbook/dispose. `command(projectId,command:WorkflowCommand):Promise<CommandResult>` uses same exact union and decimal strings. Export `WorkflowTarget={projectId,kind,id}`. Add optional `bootstrap:WorkflowBootstrap` to MountOptions.
- Child workspace props: `{api,project:ProjectDetail,onChanged(result:CommandResult):void,onOpen(target:WorkflowTarget):void,onDirty(key:string,dirty:boolean):void,readOnly:boolean}`; no actor or role prop determines permissions.

- [ ] Write component tests for member bootstrap avoiding all legacy requests, named order form submission, fixed revision readback, original/current commitment, API409 preserving draft, active dataset label and no invented enabled navigation. Use Vitest fetch mocks checking exact DTO; do not mock UI into fixed success.
- [ ] Run `npm --prefix webui test -- src/workflow/api.test.ts src/workflow/orders.test.tsx src/App.test.tsx`; see missing implementation failures.
- [ ] Implement A's usable forms and new-project/member management entry, typed API and capability branch in App. Inputs include source/evidence/units and object selectors; use API-derived choices and versions. Existing users retain full legacy shell and handbook; ordinary workflow members do not issue legacy reads. Reuse ConsoleShell dirty/handbook behavior and field components where appropriate; no generic raw JSON textarea. Show only A workspaces now; later tasks extend them.
- [ ] Run MF `npm --prefix webui test -- src/workflow/api.test.ts src/workflow/orders.test.tsx src/App.test.tsx` and `npm --prefix webui run build`; require pass. Run MF `python -m pytest tests/workflow -q`, PF bridge tests from A1. Commit `feat: expose scoped order and engineering workflow forms`.
- [ ] Reviewer checks A actions/interfaces against design and records source commits; root proceeds to B without user checkpoint. A expected acceptance coverage: E01/E02/E03/E11/E12/E18 authorization groundwork/E25/E29/E30 infrastructure/E32 isolation. Do not mark F01–F04 complete.
