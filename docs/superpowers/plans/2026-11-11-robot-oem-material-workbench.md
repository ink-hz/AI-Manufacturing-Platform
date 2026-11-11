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

- [ ] Add HTTP tests for the real harness: outsider isolation, inactive/read-only access, invalid pagination, unknown filter IDs, manual/mock provenance, stable pagination with full-scope counts, and no mutation after a read.

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

- [ ] Run `PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest -q tests/workflow/test_material_control.py`; record the expected missing-route failure.
- [ ] Implement read models using existing authorized SQL transactions, effective supply/quality facts, `supply.balance`, existing value readers and business clock. Validate/filter project, work order and requirement scope before returning any records. Bound result sets and mark partial evidence instead of implying completeness. All reads are non-accounting.
- [ ] Provide display-friendly work-order titles, existing object detail values for expedites/handoffs, receipts with effective inspected quantities, issue marks, and source provenance. Use planned start only as an explicitly labeled proxy need time; never silently treat it as authoritative component need time. Return unknown timing risk when inputs are missing.
- [ ] Run projection plus supply/expedite/handoff regressions, self-review, commit only task-owned files, and write `.superpowers/sdd/robot-material/task-1-report.md` with red/green evidence, contracts and limitations.

## Task 2: Durable IQC and trace collaboration

**Files:** Create `workflow/material_task_models.py`, `workflow/material_task_schema.py`, `workflow/material_tasks.py`, `workflow/material_task_reader.py`; modify `commands.py`, `contracts.py`, `service.py`, `schema.py`, `store.py`, `material_control_api.py`, plus focused tests `tests/workflow/test_material_tasks.py`.

**Interfaces:** New object kind `material_task`, command actions `material_task.open`, `material_task.accept`, `material_task.progress`, `material_task.verify`, `material_task.close`, `material_task.cancel`. GET `/projects/{project_id}/material-tasks?limit=50&offset=0` and GET `/material-control/tasks?project_id=...` expose scoped tasks. Existing `object_detail` exposes task detail; commands use the existing project commands endpoint.

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

- [ ] Add meaningful lifecycle/security tests before handlers: schema24 migration and restart, duplicate same inspection/same trace scope, CAS and operation replay, cross-project references, invalid/inactive assignee, unauthorized and revoked actors, designated acceptance, immutable history, non-accounting invariants.
- [ ] Add IQC test: receiving 20 and inspecting 12 accepted/8 rejected permits inspection-scope verification/closure but keeps material shortage and rejected quantities unchanged.
- [ ] Add trace tests: original handoff20 with actual receipt18 remains incomplete; progress found2 is not receipt; explicit compatible signed supplemental handoff2 can be linked as evidence; reject unrelated/cross-project/wrong lot/work-order/unit/receiver and already allocated evidence; formal discrepancy outcome remains distinguishable from full receipt.
- [ ] Observe failures with `pytest -q tests/workflow/test_material_tasks.py`, then implement an additive schema25 migration and registered typed commands/readers. Resolve active users through host directory, reuse source/actor audit, roles and existing project CAS/idempotency machinery. Assignee must have current project/role/qualification; acceptance only by designated person.
- [ ] Maintain pending/processing/verification/closed/cancelled collaboration states and explicit outcomes; task-state completion never manufactures source results. A revoked assignee can be replaced by an authorized coordinator through a recorded reassignment path while retaining current responsibility until accepted; expose any added command in the report.
- [ ] Attach material tasks to project/global responsibility lists without broadening unrelated project access. Add full-scope counts for project views without depending on one result page.
- [ ] Run targeted tasks, authorization, schema/restart and source invariants tests. Commit owned changes and write `.superpowers/sdd/robot-material/task-2-report.md`.

## Task 3: Integrate five workbench views

**Files:** Create `webui/src/workflow/materialControl/{types,api,presentation,MaterialControlWorkspace,MaterialControlOverview,MaterialTaskPanel,MaterialFlowPanel}.ts[x]` and CSS; modify `workflow/api.ts`, `WorkflowHome.tsx`, `SupplyWorkspace.tsx`, `GlobalTasks.tsx`, `labels.ts`, `types.ts` only where needed. Add focused Vitest interaction tests.

**Interfaces:** Extend `createWorkflowApi` through `materialControlApi(request)` with overview/project/tasks methods matching Tasks1/2 and typed material-task commands through existing project command endpoint. Keep existing `WorkflowApi` consumers compatible. New components accept existing `api`, current project/actor/permissions, `readOnly`, `requestLeave`, `onDirty`, reload/open/return hooks as appropriate.

- [ ] Add failing tests that click project → material requirement → expedite → IQC/trace task using real component state; cover loading/failure/empty/partial coverage, stale project switch, role/read-only, draft preservation, units and provenance, no phantom totals.
- [ ] Build project execution overview inside current workbench. Add material-control default to OEM supply workspace alongside existing supply/handoff tabs; maintain deep actions to existing forms and history.
- [ ] Implement requirement filtering/detail with exact source quantities and a labeled need-time proxy. Existing expedite open/progress/close uses typed commands, object ID and project-version reload; IQC actions use explicit receipt object and current permitted assignee lookup, not raw UUID entry.
- [ ] Implement task accept/progress/verify/close/cancel/reassignment, supported existing MES result link, and trace partial-found evidence/compatible receipt selection. Show source states separately and preserve original signed handoffs. Human inputs are concise named fields; no JSON/configuration fields in user flow.
- [ ] Integrate current-user material tasks into `GlobalTasks` or equivalent shared task section with clear scope and counts, direct drilldown and contextual return. Changes cannot retire pending drafts silently.
- [ ] Run meaningful Vitest interaction tests, existing workflow components, TypeScript build and bundle checks. Commit owned UI changes and write `.superpowers/sdd/robot-material/task-3-report.md`.

## Task 4: Test MES connection and evidence readiness

**Files:** Use ignored source-checkout private configuration; create a focused diagnostic/evidence utility under `tools/mes/` only if existing CLI cannot safely capture required metadata. Document factual results in `docs/reviews/2026-11-11-robot-oem-material-integration.md`.

- [ ] Perform one bounded GET of the test login page, retaining response privately and reporting only contract/site metadata. Do not guess site IDs.
- [ ] If the observed form matches the existing transport contract, update only the private test configuration with the observed site and enable diagnostic login. Use the existing audited CLI `diagnose --live` with a distinct test audit file.
- [ ] Enable only fixed read profiles verified against the test application, query one page/one row for a known-scope sample, retain raw evidence privately, and record source environment and missing relationships. No arbitrary SQL or business mutation.
- [ ] If unreachable or changed, retain the exact transport/contract failure and complete offline adapter tests; source coverage stays missing. Credentials never appear in logs/docs/review packages and production configuration is not repointed.
- [ ] Map actually observed interfaces to full-scope data requirements and record which remain unverified; native data ingestion beyond verified semantics is not fabricated.

## Task 5: Integration, review and safe handoff

**Files:** New feature regression evidence under `docs/verification/`; approved design/plan/checklist updates; only narrowly necessary host integration changes if required by real route checks.

- [ ] Run read and mutation flows together over actual local FastAPI HTTP and persistent SQLite. Cover partial IQC, original18/20 plus supplemental2, denial/revocation/replay/restart, unchanged inventory and legacy records.
- [ ] Run backend workflow regression, access-layer regression, UI regression and production bundle. Record distinct environment-dependent exclusions rather than silently skipping failures.
- [ ] Review full feature diff against all 13 spec sections, fix Critical/Important findings and rerun covering tests. Include any Minor review items in the ledger.
- [ ] Verify original checkout preimages against `.superpowers/sdd/robot-material/baseline-files.json` before transferring owned changes back. Refuse overwriting concurrently changed files; reconcile them narrowly.
- [ ] Produce commits, verification records and a concrete deployable candidate. Inspect current deployment mechanism/baseline before deciding production cutover; no blind release to a shared host.

## Execution status

- [x] Approved product design and source workspace inventoried.
- [x] Managed isolated worktree prepared; source access code preserved as uncommitted baseline.
- [x] Baseline: 96 backend supply/expedite/handoff tests and 25 related UI tests passed.
- [ ] Task1.
- [ ] Task2.
- [ ] Task3.
- [ ] Task4.
- [ ] Task5.
