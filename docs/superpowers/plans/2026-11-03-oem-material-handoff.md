# OEM Material Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an OEM material handoff flow that records the actual sender, designated receiver, quantity, location and discrepancies, with a compact product experience.

**Architecture:** Extend the existing typed command/object registries and additive SQLite migrations with a non-accounting `material_handoff` object. Integrate authorized tasks, existing supply navigation and React forms; preserve the current CAS, idempotency, audit and host authentication boundaries. Execute against the accepted [design](../specs/2026-11-03-oem-material-handoff-design.md).

**Tech Stack:** Existing Python 3.11 / FastAPI / Pydantic / SQLite and React 19 / TypeScript / Vitest. No new runtime dependencies.

## Global Constraints

- Current business scope is OEM; new handoff writes require `project.mode == "oem"`. Preserve existing projects and historical data.
- `material_handoff` is an attributable manual handoff record, never an inventory, reservation, IQC, consumption, ownership or SAP posting operation.
- Same-batch splits remain separate records; do not claim the final record's location represents the entire batch.
- Reuse existing operation UUID idempotency, project CAS, live permissions, CSRF, authorized source profiles and audit.
- Only the designated, currently authorized receiver may sign receipt; configuration administrators cannot impersonate another receiver.
- All object lists, tasks, member lookups and history are scoped and bounded before serialization; preserve cross-project and revoked-role isolation.
- Migration is additive schema21→22; preserve all pre-existing workflow and authority rows and the old engineering `handoffs` table.
- UI must use business fields and existing object/member choices; no UUID, JSON, source-system, source-version or operation-ID entry.
- Keep truthful manual/demo labels visible; lower-frequency evidence and history may be expanded on demand.
- No new top-level sidebar item. Use the existing supply workspace and global ledger, preserving return context and drafts.
- Existing source workspace has unrelated uncommitted documents. Work only in `/Users/neo/.codex/worktrees/a065/AI-Manufacturing-Platform`; commit only task-owned code/tests/spec/plan files explicitly, never `git add -A`.
- Do not deploy, modify production data or claim real WMS/MES/ERP/PDA integration.

## Baseline

- Source commit: `f9bdeb5`; current revised document baseline copied separately without committing it.
- `PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform python3.11 -m pytest -q tests/workflow/test_arrivals.py tests/workflow/test_bounded_queries_history.py tests/workflow/test_admin_full_access.py`: 21 passed.
- `WORKFLOW_TEST_PYTHON=/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx --reporter=dot`: 273 passed. Existing unrelated act warnings remain in legacy HTTP form tests.
- Private E30 requires its fixture launcher; run separately via the Python acceptance entry, not as a bare Vitest test.

### Task 1: Typed handoff backend, migration and responsibility tasks

**Files:**
- Create: `src/manufacturing_platform/workflow/material_handoff_models.py`, `material_handoff_schema.py`, `material_handoffs.py`, and a separate reader module if needed to keep responsibilities clear.
- Modify: `commands.py`, `contracts.py`, `schema.py`, `store.py`, `service.py` in the same package.
- Test: `tests/workflow/test_material_handoffs.py`; adjust existing exact-registry/schema assertions only where behavior genuinely changes.

**Interfaces:**
- Produces: four registry actions `material_handoff.record`, `material_handoff.receive`, `material_handoff.resolve`, `material_handoff.cancel`; object kind `material_handoff`.
- Models: `RecordMaterialHandoff`, `ReceiveMaterialHandoff`, `ResolveMaterialHandoff`, `CancelMaterialHandoff`, `MaterialHandoff`.
- State: `pending | received | disputed | resolved | cancelled`; precise fields and rules are in the design sections 2–3.
- Read API remains existing `/projects/{project_id}/objects/material_handoff`, object detail and global `/objects/material_handoff`.
- Read DTO must provide `id`, `kind`, `state`, `material_lot_id`, optional `work_order_id`, service-generated `handoff_number`, `quantity`, `unit`, `from_location`, `to_location`, `sender_id`, `sender_name`, `receiver_id`, `receiver_name`, `occurred_at`, `recorded_at`, `note`, `source`, optional `receipt`, `resolution`, `cancellation`.
- `receipt` has `received_quantity`, `received_location`, `note`, `actor_id`, trusted `actor_name`, `occurred_at`, `recorded_at`; resolution/cancellation preserve their reason/text, actor and recorded time.
- Creation roles: warehouse/supply/production; receive roles include those plus project_owner, but exact designated identity is mandatory. Resolve/cancel require original sender or project_owner/configuration_admin, plus current role authorization.
- Expose domain `authorize(...)` for actor/party checks before replay, while transition validation belongs in handlers after replay. Expose read-capability filtering so non-receivers never see a receive action.
- Extend the existing bounded member-profile resolution path for creation; resolve profiles outside transactions with policy/CAS/replay ordering preserved. In the write transaction revalidate the target member/role before a new creation.
- Pending tasks belong to receiver, disputed tasks to sender, category `business`; integrate into existing task limits/truncation and object details.

- [ ] **Step 1: Add failing real-API tests.** Use `WorkflowHarness.order_workorder(mode="oem")`, existing `material.define` and scoped grants. Capture stock/inspection/reservation/consumption/authority rows before and after. At minimum implement tests named:

```python
from uuid import uuid4
from .conftest import USERS

def test_handoff_real_api_receipt_and_nonaccounting(workflow):
    w = workflow
    p, _, wo, _ = w.order_workorder(mode="oem")
    w.grant(p["id"], "warehouse", ["warehouse"])
    w.grant(p["id"], "production", ["production"])
    lot = w.command(
        p["id"], "material.define", material_id="OEM-001", lot_id="LOT-001",
        owner_id="Customer 1", unit="kg", scale=3, expiry="2027-12-31",
        source=w.source(str(uuid4()), object_type="material_lot"),
    )["object_id"]
    tables = ("material_lots", "supply_receipts", "iqc_results", "reservations", "material_consumption")
    def stock_rows():
        with w.db() as tx:
            return {t: [tuple(r) for r in tx.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}
    before = stock_rows()
    result = w.command(
        p["id"], "material_handoff.record", actor_name="warehouse",
        material_lot_id=lot, work_order_id=wo["id"], quantity="1.250", unit="kg",
        from_location="仓库 A", to_location="产线 B", receiver_id=str(USERS["production"]),
    )
    handoff = result["object_id"]
    assert w.object(p["id"], "material_handoff", handoff)["state"] == "pending"
    w.command(
        p["id"], "material_handoff.receive", actor_name="production",
        handoff_id=handoff, received_quantity="1.250", received_location="产线 B",
    )
    assert w.object(p["id"], "material_handoff", handoff)["state"] == "received"
    assert stock_rows() == before
```

Add separate executable tests for short/over/zero receipt, wrong location, invalid state, duplicate operation, future/backwards time, bad unit/precision, same sender/receiver, invalid membership, revoked roles, outsider, non-OEM and unchanged authority rows. Test cancellation and discrepancy resolution preserve original facts, plus restart/task pagination and schema21 upgrade. Build a schema21 fixture using the previous schema/migration boundary, not by changing a current metadata number while leaving new tables present.

- [ ] **Step 2: Run the new tests and record the expected missing-feature failure.**

`PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform python3.11 -m pytest -q tests/workflow/test_material_handoffs.py`

- [ ] **Step 3: Implement minimal models, additive tables and domain handlers.** Use existing `Quantity` / `NonnegativeQuantity`, strict `Name` / `Text` and `AwareDatetime`; copy the non-accounting registration pattern from `arrival.py`. Add `HANDOFF_SCHEMA` to fresh `SCHEMA`, and a transactional 21→22 step in `store.py`. Keep receipt, resolution and cancellation records immutable once written.
- [ ] **Step 4: Register readers and responsibility-aware actions/tasks.** Validate all relation project ownership in SQL, preserve actor identity and distinguish pending destination from actual receipt. Keep source as service-generated manual evidence, with domain event identity and business time. Enforce non-OEM action applicability in reads and commands without altering legacy actions.
- [ ] **Step 5: Verify targeted regression and commit task-owned files.**

`PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform python3.11 -m pytest -q tests/workflow/test_material_handoffs.py tests/workflow/test_arrivals.py tests/workflow/test_bounded_queries_history.py tests/workflow/test_admin_full_access.py tests/workflow/test_action_capabilities.py tests/workflow/test_restart.py`

Expected: all selected tests pass. Record red and green commands/output in the task report. Commit explicit backend and test paths only with message `feat(workflow): record attributable OEM material handoffs`.

### Task 2: Compact handoff product flow and real HTTP frontend proof

**Files:**
- Create: `webui/src/workflow/materialHandoffTypes.ts`, `MaterialHandoffWorkspace.tsx`, `forms/MaterialHandoffForms.tsx`, `details/MaterialHandoffDetails.tsx`, `materialHandoff.test.tsx`, `materialHandoffHttp.test.tsx`.
- Modify: `types.ts`, `labels.ts`, `sourcePresentation.ts` if needed, `StatusBadge.tsx`, `navigationContext.ts`, `oemNavigation.ts`, `SupplyWorkspace.tsx`, `WorkflowDetail.tsx`, `WorkflowApp.tsx` and existing relevant navigation tests.
- Reuse: `forms/shared.tsx`, `GlobalLedger.tsx`, `GlobalTasks.tsx`, `api.ts` and `httpTestHost.ts`.

**Interfaces:**
- Consumes: Task 1 actions and DTO through existing API client methods; keep field names identical.
- Add handoff command/value unions and object kind without widening known types to arbitrary strings/JSON.
- Inside supply, make the OEM primary path “物料交接” and retain a clear “供应与到货” path for existing functions. Legacy non-OEM project paths remain accessible without advertising new handoff actions.
- Global supply ledger gains a “物料交接” tab and routes its objects/actions to the supply workspace. Opening a detail, choosing a permitted action, saving and returning must retain project/filter context.
- UI labels: “发起物料交接”, “确认接收”, “处理差异”, “取消交接”; states “待接收”, “已接收”, “待处理差异”, “差异已处理”, “已取消”.
- Form record fields: “物料批次”, “交接数量”, “交出位置”, “送达位置”, “接收人”; unit derived and displayed. Optional “关联工单”, “发生时间”, “备注” under additional information. Receiver choices use real scoped members and page explicitly as needed.
- Receive defaults actual quantity and location from selected handoff; expose “实收数量”, “实际接收位置”, conditional “差异说明”. Do not ask to re-enter the record identity or unit.
- Ledger focuses record, batch, quantity/unit, from/to or actual location, parties and current state; filter pending/disputed/all within the explicitly loaded range, with pagination and coverage visible. Do not claim a global state count from a partial page.

- [ ] **Step 1: Add failing component tests for compact forms, assigned actions, location/quantity differences, draft retention and stale project responses.** Use actual user-visible labels and command payload assertions, not implementation-only render snapshots.
- [ ] **Step 2: Run the new component tests to observe the missing-feature failure.**

`npm test -- src/workflow/materialHandoff.test.tsx --reporter=dot`

- [ ] **Step 3: Implement the typed workspace, forms and detail routing.** Reuse abort/generation and dirty-state lifecycles. Send ISO-aware timestamps only when edited; otherwise allow backend business-time defaults. Keep technical provenance in expandable detail while manual status remains visible.
- [ ] **Step 4: Add and run real HTTP tests.** Use `startHttpHost()` with two separately authenticated real users, create an OEM project and lot through API, grant warehouse/production roles, then submit actual React forms. Verify persisted receiver, quantity/location, disputed state and resolution after reload; snapshot unrelated stock rows through the existing test fixture where available. Also prove a non-assigned receiver has no receive action and receives server rejection if forced.

`WORKFLOW_TEST_PYTHON=/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python npm test -- src/workflow/materialHandoff.test.tsx src/workflow/materialHandoffHttp.test.tsx --reporter=dot`

- [ ] **Step 5: Run frontend regression and bundle check, then commit task-owned files.**

`WORKFLOW_TEST_PYTHON=/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx --reporter=dot`

`npm run test:bundle`

Expected: selected tests and existing suite pass, TypeScript/IIFE bundle check passes. Do not include `node_modules`, source materials or unrelated documents. Commit message `feat(ui): simplify OEM material handoff and receipt`.

### Task 3: Requirements reflection, product simplification and integration evidence

**Files:**
- Create: `docs/oem-material-handoff-iteration-2026-11-03.md` with requirement mapping, actual implementation status, product decisions, migration and validation evidence.
- Modify only necessary current R06/feature descriptions in `docs/manufacturing-workbench-product-design.md` and `docs/oem-ai-manufacturing-platform-discussion.md`; retain independently revised user baseline and separate current implementation from source-system integration.

**Interfaces:**
- Consumes tested Tasks 1–2. Produces a concise follow-up backlog distinguishing required integration, optional convenience and deferred complexity.

- [ ] **Step 1: Recheck four core questions.** Record where sender/receiver, quantity, location and unresolved ownership are shown, which fields are defaulted, and where exception resolution is located.
- [ ] **Step 2: Remove redundant new UI fields/actions identified in that pass and rerun only their affected tests.** Preserve manual provenance, original facts, permissions and discrepancy notes; do not remove mandatory business constraints to reduce visual density.
- [ ] **Step 3: Document the product choices.** Keep: one handoff record, actual recipient, quantities/locations/times, discrepancy task and immutable history. Derive/default: unit, operation identity, record number, default receipt quantity/location, source. Collapse: optional work-order/time/notes and full provenance/history. Defer: approval designer, separate warehouse master data, AI summaries without evidence and device integrations.
- [ ] **Step 4: Verify final backend scope, HTTP UI, private E30 and bundle only once on the accepted final code.** Run the Task 1 targeted regressions, Task 2 frontend suite and bundle. Run private E30 using:

`TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform WORKFLOW_ACCEPTANCE_CASES=E30 PYTHONPATH=src python3.11 -m pytest -q tests/workflow/test_acceptance.py::test_e30`

Record actual results and limits, including that no production cutover or external ERP/MES/WMS calls occurred. A root with copied docs and committed code may be dirty by design; do not clean user files.
- [ ] **Step 5: Final review, then integrate only the accepted task changes back to the user's source checkout.** First check an explicit code/test/new-design/new-plan patch against the source workspace, apply without replacing unrelated documents, and verify source matches accepted isolated code. Preserve the revised document fixes and their history. Finish with working paths, test outcomes and real integration dependencies.
