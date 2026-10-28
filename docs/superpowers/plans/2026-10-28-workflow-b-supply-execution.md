# Workflow B Supply Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver materials, authoritative reservation, controlled trial/bulk execution, stoppage recovery and engineering change boundaries.

**Architecture:** Extend A's normalized domain and command dispatcher; keep authority state in a separate SQLite. Durable outbox requests and queried receipts span the two stores without pretending they share one transaction.

**Tech Stack:** Existing Python/FastAPI/Pydantic/sqlite3/pytest/httpx; React19/TypeScript/Vitest. No ERP or MRP engine.

## Global Constraints

- “库存预留由权威系统原子接受。”
- “开工分为首件试做与批量执行”。
- “不可变版本/事实追加，纠正通过新事件表达。”
- [Technical design](../specs/2026-10-28-manufacturing-workflow-technical-design.md) and A interfaces are binding. Same MF/PF worktrees and isolated datasets. No production data writes, browser automation, or role selector.
- Separate original/current promises, requested/confirmed balances, trial/bulk scopes, old/new revisions. Dependencies: A1–A4 reviewed and passing. B does not claim final quality/delivery acceptance.

---

## Task B1: Versioned plans, supply, receipts and IQC quantities

**Files:** Create MF `src/manufacturing_platform/workflow/{supply_models.py,supply.py}` and `tests/workflow/test_supply.py`. Modify workflow schema/commands/service/queries/readiness and `webui/src/workflow/{types.ts,SupplyWorkspace.tsx,forms/SupplyForms.tsx,supply.test.tsx}`.

**Interfaces:** Produces strict plan.receive, supply.commit/receive/inspect, material.define from action catalogue. `supply.available(tx,project_id,requirement_id,now)->MaterialBalance(required,received,qualified,reserved,shortage,unit,cutoff,source_version)`; shortage uses confirmed reservations for this WO, not all available or in-transit quantities. Source commits and receipt lines persist separately. `Requirement` includes material_id,owner_id,unit,q_atoms,work_order_id,plan_id,execution_scope (trial/bulk/common). Source plan specifies scoped quantities; trial readiness checks applicable trial/common requirements rather than full bulk demand; no local BOM expansion.

- [ ] Write API tests E05–E09 for100 required/80qualified/20in-transit; receipt20 with IQC15/5; replacement5. Assert receipt, accepted, rejected and shortage separately after reopen; reject wrong owner, frozen, expired, wrong unit/precision/cutoff. Check repeated partial receipt id doesn't increment twice and supplier promise amendment retains original.

```python
def test_received_is_not_qualified(workflow):
    p, requirement, commitment = workflow.material_requirement(required='100', qualified='80')
    receipt = workflow.receive(p['id'], commitment['id'], quantity='20')
    before = workflow.balance(p['id'], requirement['id'])
    assert before['qualified'] == '80'
    workflow.inspect(p['id'], receipt['id'], accepted='15', rejected='5')
    after = workflow.balance(p['id'], requirement['id'])
    assert after['qualified'] == '95'
    assert workflow.object(p['id'], 'requirement', requirement['id'])['unqualified_quantity'] == '5'
```

- [ ] Add `.material_requirement/.receive/.inspect/.balance` helpers to existing workflow fixture as public API sequences. Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_supply.py -q`, expect unmet behavior failures.
- [ ] Implement typed normalized supply tables and invariant checks, append revisions, scope/ownership/cutoff enforcement. Apply IQC only with live quality qualification. Record original rejected quantity forever; correction uses new receipt/inspection event. Plan incoming order/revision version mismatch generates visible exception without confirming plan. Extend readiness through actual accepted reservations (until B2 these remain blocked).
- [ ] Build material table with requirement, in-transit, received, qualified, confirmed reservation, shortage and cutoff columns plus supplier/customer delivery forms and named evidence fields. Test form parsing/labels and failure preservation; run `npm --prefix webui test -- src/workflow/supply.test.tsx` and Python test. Commit `feat: track versioned supply and qualified material quantities`.

## Task B2: Stateful authority adapter and durable exchange lifecycle

**Files:** Create MF `src/manufacturing_platform/workflow/{exchange_models.py,exchanges.py,adapters/__init__.py,adapters/base.py,adapters/mock_store.py,adapters/mock.py,imports.py}` and `tests/workflow/{test_exchanges.py,test_reservation_races.py,test_imports.py}`. Modify schema/commands/service/supply/readiness and UI `ExchangeWorkspace.tsx`, `forms/SupplyForms.tsx`, types/API tests.

**Interfaces:** Exact AuthorityAdapter/ExternalRequest/ExternalReceipt/AuthoritySnapshot contracts from technical design. `ExchangeService.prepare(tx,context,request)->UUID`, `.dispatch(actor,project_id,exchange_id)->CommandResult`, `.query(actor,project_id,exchange_id)->CommandResult`, `.apply(tx,context,receipt)->MutationResult`. `parse_import(content:bytes,format:Literal['json','csv'],object_type:ImportObjectType)->list[TypedInboundRecord]`; no direct DB writes during parse. Add `source.pull(system,object_type,external_id)` to obtain authoritative records from configured adapter snapshots; incoming server data always validated, source mode assigned by adapter. Mock receipt/IQC/customer facts are generated in the isolated external authority and pulled, never inserted into platform success rows. Manual supply.receive/inspect remains labeled manual and cannot update authority stock. Add `source.import` strict command with object_type and bounded typed rows to commands union and API schema; forms/file selection parse locally or send bounded base64 file via dedicated action `source.import_file(format,object_type,content_base64)` max1MB, service parser handles validation. Both commands use same domain validators and ACL. API whitelist unchanged because command route stays fixed.

- [ ] Write concurrent authority race E10, replay/conflict E25, timeout-after-commit E26, stale receipt E27, changed-detail-same-total/reject E28, parse failure E09 tests. Use two DB connections/threads, barrier before submit; no fake success from expected assertions.

```python
def test_timeout_queries_existing_reservation(workflow):
    p, req, lot = workflow.reserve_ready(stock='100', requested='80')
    workflow.authority_fault('timeout_after_commit')
    request = workflow.command(p['id'], 'reservation.request', work_order_id=req['work_order_id'],
        requirement_id=req['id'], lot_id=lot['id'], quantity='80', unit='ea')
    workflow.dispatch(p['id'], request['exchange_id'], expected_phase='unknown')
    assert workflow.authority_balance(lot['id']) == '20'
    workflow.reopen()
    workflow.query_exchange(p['id'], request['exchange_id'])
    assert workflow.balance(p['id'], req['id'])['reserved'] == '80'
    assert workflow.authority_operation_count(request['exchange_id']) == 1
```

- [ ] Add fixture helpers using real platform API for request/dispatch/query and mock adapter boundary for fault/state inspection only. Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_exchanges.py tests/workflow/test_reservation_races.py tests/workflow/test_imports.py -q`; expect initial failures.
- [ ] Implement pending outbox and separate authority store. Dispatcher commits intent before external call, releases main DB lock, submits using stable business key, saves reply separately. If process dies after submit, pending/unknown status survives and next action must query; do not blindly retry. Authority hashes canonical input and atomically accepts once; same key changed payload409. Receipt application checks hash, source version, sequence, unit/owner/quantity and project references before changing confirmed quantities. Partial accepts persist remainder. Explicit rejection leaves no posted state. Query after uncertainty idempotently applies existing receipt. Avoid network callbacks inside SQLite write transaction.
- [ ] Implement exact-source import parsing, line errors, all-or-nothing validation per file batch, source identity assigned by configured adapter. Store received/validated/approved/accepted/posted stages separately. Reconciliation compares keyed detail maps before sums; creates owned exceptions with resolutions and audit. Show exchange detail with retry/query distinctions and mock badge, no “production connected”.
- [ ] Run named tests; assert both DBs' totals and operation counts after reopen. Commit `feat: reconcile durable workflow exchanges with stateful mock authority`.

## Task B3: Trial/bulk production, execution genealogy and interruptions

**Files:** Create MF `src/manufacturing_platform/workflow/{execution_models.py,execution.py}` and `tests/workflow/test_execution.py`; create `webui/src/workflow/{ExecutionWorkspace.tsx,forms/ExecutionForms.tsx,execution.test.tsx}`. Modify readiness/engineering/commands/schema/queries/mock adapter.

**Interfaces:** Implements unit.register, production.start/interrupt/resume, execution.record, first_article.record. `execution.eligible_units(tx,project_id,work_order_id)->list[Unit]`; units fixed revision and unique SN. Expose `TestEvidenceReader` protocol `complete_pass(tx,project_id,test_id,unit_id,revision_id)->bool`; C1 implements authoritative test queries. B3 does not fake PASS; fixture for B-level first article protocol tests supplies complete typed test evidence, final API integration uses C1.

- [ ] Write E12–E15 tests: trial1 of WO5 may start after accepted reserve/approval/calibration without first article; bulk4 blocked until complete first article; approved scope total ≤5. Unknown SN, duplicate source event, wrong program/station/firmware, invalid material owner/quantity all cannot increment confirmed output. Stop on shortage, persist linked S3/S4 exception/timestamps, replenish/replan/re-evaluate before authoritative resume.

```python
def test_trial_is_not_blocked_by_its_own_first_article(workflow):
    p, wo, units = workflow.ready_for_trial(quantity='5', trial_quantity='1')
    trial = workflow.start(p['id'], wo['id'], mode='trial', unit_ids=[units[0]['id']])
    assert trial['exchange_id']
    workflow.dispatch(p['id'], trial['exchange_id'], expected_phase='accepted')
    blocked = workflow.start(p['id'], wo['id'], mode='bulk', unit_ids=[u['id'] for u in units[1:]], expected_status=409)
    assert 'first_article' in blocked['blocking_reasons']
```

- [ ] Add fixture `.ready_for_trial/.start` using API plus authority seed stock. Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_execution.py -q`, see failures.
- [ ] Implement explicit trial and bulk accepted scopes with per-SN authorization and shared quantity budget. Derive readiness by mode; bind first article to same revision/route/test/calibration evidence. Record actual material-use edges per SN, consumption ownership, source event identity and recorded/occurred timestamps. Separate rework-route execution from initial route; C1 will invoke it. Failed events have durable rejected source records without good-count changes; valid correction references superseded event. Stop/resume request needs authority response, not local toggle.
- [ ] Implement actual WO cards, fixed version, readiness blockers, trial/bulk forms, SN registration, per-station material/measurement links and interruptions. Test mode distinction, editable operational fields and draft protection. Run Python and `npm --prefix webui test -- src/workflow/execution.test.tsx`; commit `feat: execute bounded trial and bulk workorder scopes`.

## Task B4: ECO impact and explicit change boundaries

**Files:** Create MF `src/manufacturing_platform/workflow/{eco_models.py,eco.py}` and `tests/workflow/test_eco.py`; modify engineering/execution/commands/schema/mock adapter and `webui/src/workflow/forms/EngineeringForms.tsx` plus `engineering.test.tsx`.

**Interfaces:** Implements eco.open/disposition/switch/close; `eco.impacts(tx,project_id,old_revision_id)->list[EcoImpact]`; `eco.switch` returns new workorder ID when splitting unexecuted scope. Existing workorder snapshot immutable; order allocations transferred only after external cancellation/creation receipt and in one domain transaction.

- [ ] Write E04/E11/F02 component path: old5 executed M1, new15 M2; retain old unit versions and history, old inventory/WIP impact unresolved prevents close. Try changing partially executed WO binding directly: reject; explicit split newWO for remaining quantity, unchanged original allocated/executed scope, sum ≤order. Customer unknown prevents OEM switch.

```python
def test_eco_cannot_close_with_unresolved_old_stock(workflow):
    p, eco, impact = workflow.open_eco_with_stock()
    result = workflow.command(p['id'], 'eco.close', eco_id=eco['id'], expected_status=409)
    assert impact['id'] in result['fields']['unresolved_impact_ids']
    assert workflow.object(p['id'], 'eco', eco['id'])['state'] == 'open'
```

- [ ] Add `.open_eco_with_stock` as public API sequence; run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_eco.py -q`, see failure.
- [ ] Implement impact enumeration for purchase, stock, WIP, assigned WO/SN; explicit disposition quantities/evidence, receipt-based switch, new readiness evaluation and preserved old snapshots. No deleting stock to make ECO close. UI shows old/new version, affected list, boundary selection, dispositions and waiting external acceptance. Run Python + `npm --prefix webui test -- src/workflow/engineering.test.tsx`, then all `tests/workflow` once for B gate. Commit `feat: control engineering changes across stock and work in progress`.
- [ ] Record B reviewer results and source commit; proceed C. Covered E04–E15/E25–E28 and foundations of E31. Final C/D tests must replace provisional B-only test evidence with real test.record API.
