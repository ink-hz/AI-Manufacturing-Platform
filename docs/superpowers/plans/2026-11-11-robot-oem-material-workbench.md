# Robot OEM Material Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the existing manufacturing platform into a project material workbench with explainable balances, expedite handling, accountable IQC tasks and material tracing.

**Architecture:** Reuse the existing workflow store, project authorization, command registry, idempotency, audit, supply facts, expedite cases and designated-receiver handoffs. Add focused read projections and typed material collaboration, then integrate five views into the existing shell. Native test-system evidence is independently verified and never relabeled as production truth.

**Tech Stack:** Python >=3.11, FastAPI, Pydantic 2, SQLite, React 19, TypeScript, Vitest, pytest.

## Global Constraints

- Approved spec: `docs/superpowers/specs/2026-11-11-robot-oem-material-workbench-design.md`.
- Use `/Users/neo/.codex/worktrees/4ce0/AI-Manufacturing-Platform`; source checkout is `/Users/neo/Developer/work/AI-Manufacturing-Platform`.
- Preserve preexisting access-layer changes copied into the worktree; never stage unrelated files or private data/configuration.
- Only test MES `http://10.10.80.177` is authorized for current integration work; credentials remain in ignored private configuration outside this worktree.
- Existing source modes remain visible; local/manual/mock balances are not native source coverage. Incomplete data never implies zero shortage or readiness.
- Quantities use Decimal/string with units, not floats; quality, allocation and transport milestones must not be summed as disjoint supply.
- Project authorization, CSRF, current roles, read-only, CAS, idempotency and audit apply to every mutation; designated receivers cannot be impersonated by administrators.
- An IQC task completes when its inspection scope has been inspected, including rejected quantity; procurement/quality dispositions continue separately.
- A trace task closing or finding stock does not create a receipt, modify inventory or silently close a shortage.
- Preserve prior business records and source identities; schema migrations are additive and must work from schema24.
- Use `/private/tmp/manufacturing-contract-py311/bin/python` with `PYTHONPATH=src`; use existing `webui/node_modules`.
- No live business writes, destructive database reset, or production cutover during development verification.
- Latest user instruction: product-first UI. Main screens show business facts, responsibility and direct actions, not implementation/status jargon, source-coverage essays or debug metadata. Put provenance/audit/technical diagnostics behind on-demand details; missing necessary data becomes a concise concrete business problem with a useful next action.

## Task 1: Authorized project and material read projections

**Files:** Create `workflow/material_control_models.py`, `workflow/material_control.py`, `workflow/material_control_api.py`; modify `workflow/api.py` only to register routes; test `tests/workflow/test_material_control.py`.

**Interfaces:** `register_material_control_routes(router, service, actor)` registers GET `/material-control/overview` and GET `/projects/{project_id}/material-control`. Queries accept `limit=50`, `offset=0`, optional UUID `work_order_id`/`requirement_id` for the project view. Frontend consumes JSON, with the stable fields below; additional evidence fields may be added without renaming these.

```python
# Overview response
{"items": [{"project_id": "uuid", "name": "name", "customer_id": "customer",
 "product": "robot", "work_order_count": 0, "requirement_count": 0,
 "open_expedite_count": 0, "unreceived_handoff_count": 0,
 "coverage_issues": [], "source_modes": []}], "total": 0, "limit": 50,
 "offset": 0, "read_at": "aware ISO timestamp"}
# Project response
{"project_id": "uuid", "project_version": 1, "read_at": "aware ISO timestamp",
 "coverage_issues": [], "source_modes": [], "work_orders": [],
 "requirements": [], "expedites": [], "handoffs": [], "receipts": [],
 "issue_marks": [], "total": 0, "limit": 50, "offset": 0}
# Requirement row
{"id": "uuid", "work_order_id": "uuid", "material_id": "code", "owner_id": "owner",
 "unit": "kg", "required": "100", "received": "80", "qualified": "80",
 "rejected": "0", "reserved": "0", "shortage": "100", "in_transit": "20",
 "need_at": "aware ISO timestamp or null", "timing_risk": "unknown",
 "coverage_issues": [], "expedite_ids": [], "receipt_ids": [], "handoff_ids": []}
```

- [x] Add HTTP tests for the real harness: outsider isolation, inactive/read-only access, invalid pagination, unknown filter IDs, manual/mock provenance, stable pagination with full-scope counts, and no mutation after a read.

```python
def test_material_projection_keeps_inspection_and_reservation_separate(workflow):
    from .conftest import BASE
    p, req, _ = workflow.material_requirement(mode="oem", qualified="80")
    r = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control")
    assert r.status_code == 200
    row = next(x for x in r.json()["requirements"] if x["id"] == req["id"])
    assert (row["qualified"], row["reserved"], row["shortage"]) == ("80", "0", "100")
    assert r.json()["coverage_issues"]
```

- [x] Run `PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest -q tests/workflow/test_material_control.py`; record the expected missing-route failure.
- [x] Implement read models using existing authorized SQL transactions, effective supply/quality facts, `supply.balance`, existing value readers and business clock. Validate/filter project, work order and requirement scope before returning any records. Bound result sets and mark partial evidence instead of implying completeness. All reads are non-accounting.
- [x] Provide display-friendly work-order titles, existing object detail values for expedites/handoffs, receipts with effective inspected quantities, issue marks, and source provenance. Use planned start only as an explicitly labeled proxy need time; never silently treat it as authoritative component need time. Return unknown timing risk when inputs are missing.
- [x] Run projection plus supply/expedite/handoff regressions, self-review, commit only task-owned files, and write `.superpowers/sdd/robot-material/task-1-report.md` with red/green evidence, contracts and limitations.

## Task 2: Durable IQC and trace collaboration

**Files:** Create `workflow/material_task_models.py`, `workflow/material_task_schema.py`, `workflow/material_tasks.py`, `workflow/material_task_reader.py`; modify `commands.py`, `contracts.py`, `service.py`, `schema.py`, `store.py`, `material_control_api.py`, plus focused tests `tests/workflow/test_material_tasks.py`.

**Interfaces:** New object kind `material_task`, command actions `material_task.open`, `material_task.accept`, `material_task.progress`, `material_task.verify`, `material_task.close`, `material_task.cancel`. GET `/projects/{project_id}/material-tasks?limit=50&offset=0` and GET `/material-control/tasks?project_id=...` expose scoped tasks. GET `/projects/{project_id}/material-control/assignees?task_kind=iqc|trace` returns currently eligible active project members with IDs and display names; IQC eligibility requires current quality role and inspection qualification (or existing administrator capability). Existing `object_detail` exposes task detail; commands use the existing project commands endpoint.

```python
{"action":"material_task.open", "requirement_id":"uuid", "task_kind":"iqc",
 "receipt_id":"uuid", "handoff_id":None, "assignee_id":"uuid", "note":"请核对待检批次"}
{"action":"material_task.accept", "task_id":"uuid"}
{"action":"material_task.progress", "task_id":"uuid", "note":"已安排核对",
 "expected_completion":None, "blocked_reason":None,
 "found_quantity":None, "found_location":None}
{"action":"material_task.verify", "task_id":"uuid", "evidence":"已核对正式结果",
 "handoff_ids":[]}
{"action":"material_task.close", "task_id":"uuid", "outcome":"fulfilled", "evidence":"依据"}
{"action":"material_task.cancel", "task_id":"uuid", "reason":"误关联"}
```

- [x] Add meaningful lifecycle/security tests before handlers: schema24 migration and restart, duplicate same inspection/same trace scope, CAS and operation replay, cross-project references, invalid/inactive assignee, unauthorized and revoked actors, designated acceptance, immutable history, non-accounting invariants.
- [x] Add IQC test: receiving 20 and inspecting 12 accepted/8 rejected permits inspection-scope verification/closure but keeps material shortage and rejected quantities unchanged.
- [x] Add trace tests: original handoff20 with actual receipt18 remains incomplete; progress found2 is not receipt; explicit compatible signed supplemental handoff2 can be linked as evidence; reject unrelated/cross-project/wrong lot/work-order/unit/receiver and already allocated evidence; formal discrepancy outcome remains distinguishable from full receipt.
- [x] Observe failures with `pytest -q tests/workflow/test_material_tasks.py`, then implement an additive schema25 migration and registered typed commands/readers. Resolve active users through host directory, reuse source/actor audit, roles and existing project CAS/idempotency machinery. Assignee must have current project/role/qualification; acceptance only by designated person.
- [x] Maintain pending/processing/verification/closed/cancelled collaboration states and explicit outcomes; task-state completion never manufactures source results. A revoked assignee can be replaced by an authorized coordinator through a recorded reassignment path while retaining current responsibility until accepted; expose any added command in the report.
- [x] A normal user can finish with one direct `material_task.close` action: it verifies fresh source facts atomically in the same transaction; do not force users through a separate verify button or technical intermediate state. Keep verify available for background/on-demand validation. IQC results already fully inspected including rejected quantities permit finish; shortage follow-up remains separate. Trace progress/found quantity alone does not permit fulfilled closure without compatible actual signed receipt evidence.
- [x] Attach material tasks to project/global responsibility lists without broadening unrelated project access. Add full-scope counts for project views without depending on one result page.
- [x] Run targeted tasks, authorization, schema/restart and source invariants tests. Commit owned changes and write `.superpowers/sdd/robot-material/task-2-report.md`.

## Task 3: Integrate five workbench views

**Files:** Create `webui/src/workflow/materialControl/{types,api,presentation,MaterialControlWorkspace,MaterialControlOverview,MaterialTaskPanel,MaterialFlowPanel}.ts[x]` and CSS; modify `workflow/api.ts`, `WorkflowHome.tsx`, `SupplyWorkspace.tsx`, `GlobalTasks.tsx`, `labels.ts`, `types.ts` only where needed. Add focused Vitest interaction tests.

**Interfaces:** Extend `createWorkflowApi` through `materialControlApi(request)` with overview/project/tasks methods matching Tasks1/2 and typed material-task commands through existing project command endpoint. Keep existing `WorkflowApi` consumers compatible. New components accept existing `api`, current project/actor/permissions, `readOnly`, `requestLeave`, `onDirty`, reload/open/return hooks as appropriate.

- [x] Add failing tests that click project → material requirement → expedite → IQC/trace task using real component state; cover loading/failure/empty/partial coverage, stale project switch, role/read-only, draft preservation, units and provenance, no phantom totals.
- [x] Build project execution overview inside current workbench. Add material-control default to OEM supply workspace alongside existing supply/handoff tabs; maintain deep actions to existing forms and history.
- [x] Implement requirement filtering/detail with exact source quantities and a labeled need-time proxy. Existing expedite open/progress/close uses typed commands, object ID and project-version reload; IQC actions use explicit receipt object and current permitted assignee lookup, not raw UUID entry.
- [x] Implement task accept/progress/verify/close/cancel/reassignment, supported existing MES result link, and trace partial-found evidence/compatible receipt selection. Show source states separately and preserve original signed handoffs. Human inputs are concise named fields; no JSON/configuration fields in user flow.
- [x] Integrate current-user material tasks into `GlobalTasks` or equivalent shared task section with clear scope and counts, direct drilldown and contextual return. Changes cannot retire pending drafts silently.
- [x] Run meaningful Vitest interaction tests, existing workflow components, TypeScript build and bundle checks. Commit owned UI changes and write `.superpowers/sdd/robot-material/task-3-report.md`.

## Task 4: Test MES connection and evidence readiness

**Files:** Use ignored source-checkout private configuration; create a focused diagnostic/evidence utility under `tools/mes/` only if existing CLI cannot safely capture required metadata. Document factual results in `docs/reviews/2026-11-11-robot-oem-material-integration.md`.

- [x] Perform one bounded GET of the test login page, retaining response privately and reporting only contract/site metadata. Do not guess site IDs.
- [x] If the observed form matches the existing transport contract, update only the private test configuration with the observed site and enable diagnostic login. Use the existing audited CLI `diagnose --live` with a distinct test audit file.
- [x] Enable only fixed read profiles verified against the test application, query one page/one row for a known-scope sample, retain raw evidence privately, and record source environment and missing relationships. No arbitrary SQL or business mutation.
- [x] If unreachable or changed, retain the exact transport/contract failure and complete offline adapter tests; source coverage stays missing. Credentials never appear in logs/docs/review packages and production configuration is not repointed.
- [x] Map actually observed interfaces to full-scope data requirements and record which remain unverified; native data ingestion beyond verified semantics is not fabricated.

## Task 5: Integration, review and safe handoff

**Files:** New feature regression evidence under `docs/verification/`; approved design/plan/checklist updates; only narrowly necessary host integration changes if required by real route checks.

Host integration identified: PF uses an exact authorization allowlist. Work on `/Users/neo/.codex/worktrees/robot-oem-material-host-20261111/AI-Agent-Platform`, branch `codex/robot-oem-material-host`, based on current local/remote master `98181603`. Respect that repository's AGENTS.md: interface-first tests, user handles browser acceptance, no production Nginx changes.

Modify only `backend/app/manufacturing_paths.py`; test `backend/tests/test_manufacturing_material_routes.py`. Add these GET contracts to `WORKFLOW_ROUTES`:

```python
("GET", "/material-control/overview"),
("GET", "/projects/{project_id}/material-control"),
("GET", "/projects/{project_id}/material-tasks"),
("GET", "/material-control/tasks"),
("GET", "/projects/{project_id}/material-control/assignees"),
```

- [x] Observe new host tests fail for absent allowlist entries, add exactly these entries and verify all role cases retain anonymous401, authenticated GET policy, denied POST/extra suffix and authenticated unavailable503/no-store behavior. Run `PYTHONPATH=backend /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q backend/tests/test_manufacturing_material_routes.py`.
- [x] Test actual MF package mount against this host after frontend build; retain project-level authorization inside MF. This patch grants no new business-write route.

- [x] Run read and mutation flows together over actual local FastAPI HTTP and persistent SQLite. Cover partial IQC, original18/20 plus supplemental2, denial/revocation/replay/restart, unchanged inventory and legacy records.
- [x] Run backend workflow regression, access-layer regression, UI regression and production bundle. Record distinct environment-dependent exclusions rather than silently skipping failures.
- [x] Review full feature diff against all 13 spec sections, fix Critical/Important findings and rerun covering tests. Include any Minor review items in the ledger.
- [x] Verify original checkout preimages against `.superpowers/sdd/robot-material/baseline-files.json` before transferring owned changes back. Refuse overwriting concurrently changed files; reconcile them narrowly.
- [x] Produce commits, verification records and a concrete deployable candidate. Inspect current deployment mechanism/baseline before deciding production cutover; no blind release to a shared host.

## Execution status

- [x] Approved product design and source workspace inventoried.
- [x] Managed isolated worktree prepared; source access code preserved as uncommitted baseline.
- [x] Baseline: 96 backend supply/expedite/handoff tests and 25 related UI tests passed.
- [x] Task1.
- [x] Task2.
- [x] Task3.
- [x] Task4.
- [x] Task5.

## Task 6: Connect fixed native MRP and IQC reads

User steering: 按完整工作流打通数据并真实测试闭环。Reuse the existing native access foundations; do not replace this with another simulated workflow or add technical status pages. Native test reads and the actual same-object business closure have separate evidence. The actual SAP and MES samples currently have incompatible component lists; a pilot order/plant is requested asynchronously and must not be guessed.

- [x] Adopt only the existing runtime SAP/MES access modules and their required unit/API/CLI tests/templates into the reviewed feature, preserving unrelated source work. Verify original preimages and record which adopted files were unchanged baseline. Native runtime must work from a clean Git export rather than relying on copied untracked modules.
- [x] Add one fixed SAP read for `BAPI_MATERIAL_STOCK_REQ_LIST`, scoped to required exact material and plant. Use current WSDL/request/response evidence in the private `stock-req-live.*` capture; empty table wrappers and detail flags are code-owned. No arbitrary XML/function/URL, MRP planning execution, automatic retries, or newly opened legacy business functions. Validate against current wire limits, preserve identifier/decimal/unit strings, bound rows/body/time, propagate SAP business rejection and persist audit intent before network. Existing automatic policy/config opt-in still governs execution.
- [x] Add registered fixed MES `iqc_receive` read at `/orbbec/iqcReceive/iqcReceiveAction!query.action`, required exact `inspNo`, optional startDate/endDate, pageNumber/pageLimit bounded to5. Match current test JavaScript `paramJson` encoding and common list envelope; callers never supply action/path/SQL. Retain service/transport/config allowlist and audit requirements. Treat IQC inspector receipt separately from warehouse or line-side receipt.
- [x] Add failing tests first for correct wire encoding, field/size limits, disallowed requests before I/O, business failure, malformed/oversized response, auth/read-only/CSRF according to existing route semantics, configuration isolation, source identity, no secret/audit leakage and existing profile compatibility. Keep native data out of mock stores.
- [x] Expose fixed typed service/API/CLI reads using existing admin boundary; no caller-supplied credentials or arbitrary source operations. Commit owned additions, run covering native access and workflow regressions, write ignored implementation report, and request independent spec/quality review.
- [x] After review, opt in only the private test configurations to the two fixed reads, invoke the actual adapters with known real scoped identifiers, retain0600 raw captures and sanitized evidence, and leave production configuration unchanged. No business-write API is part of this task.

## Task 7: Validate the actual same-object workflow

- [ ] Verify the pilot project/order, factory/site/client, component/reservation identity and unit on SAP and the designated MES test system before creating a platform binding. User pilot question remains pending; elapsed time is not an answer. Same order number or material alone is insufficient.
- [ ] Trace actual procurement/receipt line→batch→inspection→issue→line-side signed receipt/variance using verified source identifiers. Implement only the exact missing read or confirmed test operation needed by that path, with tests and source audit. Do not treat allocation plans, IQC reception, stocktake differences or returnable stock as physical line-side receipt.
- [ ] Run the platform journey with those native facts, re-read actual persisted source and platform results after each operation, and verify quantities, responsibility, quality scope and outstanding differences. Synthetic local fixtures remain regression evidence, not native acceptance.
- [ ] Publish the concrete workflow result and outstanding source/identity gaps truthfully; no production cutover, source business writes, or guessed data associations are implied by completing read adapters.

## Task 8: Mount native readers in the actual platform host

Current PF host has no SAP/MES native access mounting, despite MF's public builders. Work in the isolated PF worktree; preserve older releases, legacy/workflow availability and existing authentication.

- [x] Add exactly the fixed SAP/MES admin read/diagnostic route contracts to the existing management-only manufacturing policy, including POST `/sap/mrp/stock-requirements`. Keep ordinary project members denied, anonymous401, CSRF for POST and hard-stale503.
- [x] Use trusted optional environment path pairs `PLATFORM_MANUFACTURING_SAP_CONFIG_PATH` / `PLATFORM_MANUFACTURING_SAP_AUDIT_PATH` and MES equivalents. Construct public services/routers lazily, without opening configuration, audit or network during construction. Mount before legacy fallback with `authorize_workflow_identity` supplying current `configuration_admin`; native routers keep their own strict admin boundary. Reject partial/relative/alias path settings without logging values. A malformed/unavailable optional source never disables legacy or the controlled workflow.
- [x] Reserve exact native routes as authenticated503/no-store when unconfigured or incompatible. No arbitrary native URL/action/function or production environment change is added.
- [x] TDD policy, optional mounting, unavailable/old release compatibility, two-source independence and trusted actor cases. Validate against the real MF Git-export package after Task6, review the exact two-repository candidate and retain actual source/controlled fixture acceptance separately.

Native reader review and live acceptance: MF a05a9a3, PF 6153e319. SAP4MRPitems/SAP success; MES exactIQC-receive actual0rows. Same-object workflow closure remains pending pilot order/plant, not inferred from same-number samples. See docs/verification/robot-oem-material-workbench-2026-11-11.md.

Local integration complete: MF main3be7fa9(codeunchanged by later evidence-onlycommits),PF master6153e319. Guarded originalpreimages backedup; unrelated .gitignore/README/knowledgeREADME preserved byte-for-byte. MergedMF96focusedtests andoriginalbundlepass; mergedPF296tests pass. Runtimeassets matchreviewedworktree exactly. Task7 remainsOPEN pendingactualpilotidentity; noonlinecutover.
