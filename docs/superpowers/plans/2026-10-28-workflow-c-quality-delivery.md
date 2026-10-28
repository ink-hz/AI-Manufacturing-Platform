# Workflow C Quality Delivery Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete measured quality, independent release authorities, allocated deliveries, bidirectional trace and closed feedback loops.

**Architecture:** Add bounded quality/delivery/feedback services on A/B's transaction, fixed revisions, physical unit links and durable exchanges. Compute all quantities from underlying accepted facts and preserve failures and original events.

**Tech Stack:** Existing FastAPI/Pydantic/sqlite3/pytest/httpx and React19/TypeScript/Vitest.

## Global Constraints

- “制造、质量、客户三个独立放行结果”。
- “失败不被复测覆盖”；“只发一部分不能关闭整行”；“签收不自动表示验收完成”。
- “成本结案不自动关闭客诉”；“CAPA 有效果验证，ECO 有执行结果”。
- [Technical design](../specs/2026-10-28-manufacturing-workflow-technical-design.md), A/B contracts and isolated environments apply. Begin only after reviewed B. No browser or production mutation. Preserve whole handbook and all legacy records.

---

## Task C1: Measurements, first-pass history, nonconformance and release

**Files:** Create MF `src/manufacturing_platform/workflow/{quality_models.py,quality.py}` and `tests/workflow/test_quality.py`; create `webui/src/workflow/{QualityWorkspace.tsx,forms/QualityForms.tsx,quality.test.tsx}`. Modify schema/commands/service/queries/execution/readiness and TS DTOs.

**Interfaces:** Strict test.record, nonconformance.open/disposition, rework.complete, release.decide. `quality.complete_pass(tx,project_id,test_id,unit_id,revision_id)->bool` implements B3 TestEvidenceReader. `quality.shipment_eligibility(tx,project_id,unit_ids)->Eligibility(allowed,reasons,qualified_quantity,release_ids)` used by C2. `QualitySummary(first_tested,first_passed,final_good,scrapped,open_nonconformances)` derives SQL facts, not editable totals.

- [ ] Write E16/E17/E18/E19 and true B3 integration: 100 units initial96 pass/4fail; four rework routes with3passed/1scrap => first_passed96/final_good99/scrapped1, original failures4; no input can assert PASS without measurements/spec. Production quality approval403; platform_admin with no quality qualification403; quality-qualified member succeeds only in own project. Required customer release remains independent. Limit values must match frozen spec, not arbitrary caller ranges.

```python
def test_retest_preserves_first_failure(workflow):
    p, unit = workflow.executed_unit()
    first = workflow.test(p['id'], unit['id'], measured='12', lower='0', upper='10')
    assert first['outcome'] == 'fail'
    rw = workflow.rework(p['id'], first['id'])
    workflow.test(p['id'], unit['id'], measured='8', lower='0', upper='10', rework_order_id=rw['id'])
    detail = workflow.object(p['id'], 'unit', unit['id'])
    assert [test['outcome'] for test in detail['tests']] == ['fail', 'pass']
    assert detail['first_pass'] is False
```

- [ ] Define fixture `.executed_unit/.test/.rework` using all earlier public actions, no pre-created passing test rows. Run `python -m pytest tests/workflow/test_quality.py tests/workflow/test_execution.py -q`, fail on missing behavior.
- [ ] Implement measurements as finite Decimal values, complete required spec dimensions, version/unit consistency, calculated outcomes, numbered attempts and source idempotency. Link NC disposition to independent rework route execution and successful retest; scrap is irreversible unit exclusion with reason. Conditional release requires explicit units, finite quantity, condition scope, expiry/evidence and policy permitting concession; never qualifies an untested failed unit by default. Manufacturing needs production grant, quality needs quality_release qualification, customer receipt must match contract/customer/revision and explicit external/manual source. Every decision remains separate immutable row.
- [ ] Replace B3 protocol-only happy-path fixture with real test API integration. Implement test matrix UI with limit/program provenance, first vs retest histories, disposition/rework and three release panels. Run Python test and `npm --prefix webui test -- src/workflow/quality.test.tsx`. Commit `feat: preserve measured quality and independent release decisions`.

## Task C2: SN/box shipments, acceptance and independent closure

**Files:** Create MF `src/manufacturing_platform/workflow/{delivery_models.py,delivery.py}` and `tests/workflow/test_delivery.py`; create `webui/src/workflow/{DeliveryWorkspace.tsx,forms/DeliveryForms.tsx,delivery.test.tsx}`. Modify schema/commands/service/queries/mock adapter/TS DTOs.

**Interfaces:** shipment.request, delivery.sign/accept/resolve_issue, closure.record, ownership.reconcile. `delivery.remaining(tx,project_id,order_line_id)->DeliveryBalance(ordered,allocated,qualified,pending_shipment,shipped,signed,accepted,remaining_to_ship,remaining_to_accept,unit)`; `delivery.close_predicates(tx,project_id,kind)->list[BlockingReason]`. Shipment selection consumes exact order allocation and eligible unique unit IDs atomically; pending shipment claims prevent duplicates before external response.

- [ ] Write E21–E23:100 released, request60, receipt accepted, sign60, accept60 => remaining40/not closed; duplicateSN and41 attempts409/no accepted shipment; remaining40 completes only after sign/accept. Delayed shipping receipt cannot imply signed; signed cannot imply accepted; required issue keeps fulfillment open. Cost closed while quality issue open stays independent. OEM customer material reconciliation distinguishes consumed/scrapped/returned/balance and ownership.

```python
def test_partial_delivery_keeps_order_open(workflow):
    p, order, units = workflow.released_order(quantity='100')
    shipment = workflow.ship(p['id'], order['id'], [u['id'] for u in units[:60]])
    workflow.sign_and_accept(p['id'], shipment['id'], quantity='60')
    summary = workflow.object(p['id'], 'order_line', order['id'])
    assert summary['remaining_to_ship'] == '40'
    assert summary['fulfillment_status'] != 'closed'
    workflow.ship(p['id'], order['id'], [units[0]['id']], expected_status=409)
```

- [ ] Add `.released_order/.ship/.sign_and_accept` as full authorized API sequences. Run `python -m pytest tests/workflow/test_delivery.py -q`; fail initially.
- [ ] Implement shipment request→external accepted/posted receipt with unique pending and accepted SN claims, no over-quantity race, box membership exact-once, order links. Explicit rejected shipment can release pending claims by new audited event; unknown must query first. Sign/accept sums cannot exceed authoritative shipped/signed quantities. Acceptance issues have trusted responsible UUID and required/resolved states. Closure predicates never inherit manual S9 completion; cost evidence must label ERP/mock/manual correctly and never auto-close RMA. Ownership balances compare actual material uses and returns rather than caller totals.
- [ ] Implement shipment SN/box picker, live remaining quantities, separate receipt/acceptance forms, issue owner/resolution and three closure cards. Test failed oversized submission preserves selections. Run Python test and `npm --prefix webui test -- src/workflow/delivery.test.tsx`; commit `feat: reconcile partial delivery and independent closures`.

## Task C3: Trace, freeze receipts and RMA/CAPA change feedback

**Files:** Create MF `src/manufacturing_platform/workflow/{trace.py,feedback_models.py,feedback.py}` and `tests/workflow/{test_trace_freeze.py,test_feedback.py}`; create `webui/src/workflow/{TraceWorkspace.tsx,forms/FeedbackForms.tsx,feedback.test.tsx}`. Modify schema/commands/service/queries/mock adapter/eco/delivery/TS DTOs.

**Interfaces:** `trace.query(tx,project_id,*,sn:str|None,material_lot_id:UUID|None,limit=500)->TraceResult(nodes:TraceNode[],edges:TraceEdge[],truncated:bool)`; node types use explicit ObjectKind and reference authorized details. freeze.request, rma.open, capa.update/close. Freeze receipt applies through B2 with monotonic source sequence. `feedback.quality_blockers(tx,project_id)->list[BlockingReason]` composes C2 quality closure.

- [ ] Write E20/E24/E27: bad lot forward traversal finds exact units/orders/customers, shipped SN reverse traversal finds engineering/material/test. Another project/customer yields404 with no counts. Requested freeze visibly pending, prevents dispatch locally; accepted freeze source sequence establishes authority state; older unfreeze rejected, newer unfreeze accepted only after receipt. Delivered SN RMA links original shipment/failed test; CAPA containment/root cause/correction/effectiveness plus linked ECO actual close required. Failed effectiveness remains open.

```python
def test_pending_freeze_does_not_claim_authority_confirmation(workflow):
    p, order, units = workflow.released_order(quantity='2')
    result = workflow.command(p['id'], 'freeze.request', unit_ids=[units[0]['id']],
        lot_ids=[], state='frozen', reason='suspect material')
    detail = workflow.object(p['id'], 'unit', units[0]['id'])
    assert detail['freeze_requested'] == 'frozen'
    assert detail['freeze_confirmed'] != 'frozen'
    workflow.ship(p['id'], order['id'], [units[0]['id']], expected_status=409)
    workflow.dispatch(p['id'], result['exchange_id'], expected_phase='accepted')
    assert workflow.object(p['id'], 'unit', units[0]['id'])['freeze_confirmed'] == 'frozen'
```

- [ ] Run `python -m pytest tests/workflow/test_trace_freeze.py tests/workflow/test_feedback.py -q`, fail before implementation.
- [ ] Implement trace from typed FK edges, bounded and scoped SQL; material consumption, failed/retest history and shipment/RMA original links retained. Persist requested/confirmed freeze independently; server checks both for new delivery eligibility and disallows local unfreeze override. Add RMA source facts and ordered CAPA evidence; missing root cause/verification/ECO execution blocks close. Keep internal analysis field values human-entered evidence, no pretend AI diagnostics.
- [ ] Implement SN/lot search, navigable result/table links, affected-unit freeze selection, RMA intake and named CAPA step forms; all use same object DTOs and current project version. Run named Python/UI tests then `python -m pytest tests/workflow -q` once and `npm --prefix webui run build`. Commit `feat: trace affected units and close verified quality feedback`.
- [ ] Record C source/reviews. C completion covers E16–E24/E27 boundaries; proceed D for all36 actual acceptance and production candidate evidence, no final completion claim yet.
