# Workflow D Operable UI and Full Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a user-operable end-to-end workflow and evidence for all F01–F04 and E01–E32 scenarios.

**Architecture:** Finish domain workspaces over the same typed API, then run scenarios through authenticated real service routes with isolated stateful authority stores. Preserve scenario failures, process-restart evidence and exact source revisions separately from user visual/production acceptance.

**Tech Stack:** Existing React19/Vite/Vitest; Python pytest/httpx/sqlite3; verified PF uvicorn 0.52.1 runtime for isolated child-process HTTP tests. No new application dependency solely for a test runner.

## Global Constraints

- “主剧本从需求开始顺序执行至反馈结案，首错即停并保留现场”。
- “mock 只位于外部身份测试提供方或业务系统适配边界，逐项注明”。
- “所有 F01—F04 和 E01—E32 是目标验收范围”。
- “mock 联测、真实系统集成、生产验收和业务改善四种结论分别记录”。
- A/B/C reviewed before D final acceptance; [technical design](../specs/2026-10-28-manufacturing-workflow-technical-design.md) and [approved matrix](../../testing/manufacturing-full-workflow-acceptance.md) are binding. No lowering assertions to make a case pass, no database insertion of business success states, no browser automation, no production writes or messages.
- Normal commands run from MF worktree; PF commands explicitly state PF. Existing baseline source MF ec41b39/PF b87d88ac; final report records actual commits, not these initial values.

---

## Task D1: Integrate all daily workspaces and safe navigation

**Files:** Modify MF `webui/src/{App.tsx,types.ts,console/ConsoleShell.tsx}` and workflow types/api/WorkflowHome/WorkflowProjects/WorkflowDetail/Orders/Supply/Execution/Quality/Delivery/Trace/Exchange workspaces and domain forms. Create `webui/src/workflow/{ActionForms.tsx,workspace.test.tsx,navigation.test.tsx,trace.test.tsx}`; extend `webui/src/{App.test.tsx,index.test.tsx,HandbookReader.test.tsx}` if latter absent use existing handbook component tests in App.test.tsx. Create MF `src/manufacturing_platform/workflow/progress.py`, `tests/workflow/test_progress.py`.

**Interfaces:** All workspace props and WorkflowTarget stay A4-compatible. `project.stage` command only changes collaborator hint; `progress.aggregate(tx,project_id)->ProgressSummary(stages,blocking_objects,fulfillment,quality,cost)` uses real domain conditions. Server next_actions contains authorized action names and blocking reasons; UI does not derive qualification from display role.

- [ ] Write component tests with real named inputs/buttons for create demand→review→order→WO, supply receipt/IQC/reserve, trial/measurement/first article/bulk, NC/rework, releases, shipment/sign/accept, RMA/CAPA/ECO. Check no link points to placeholder workspaces and no form requires raw JSON. Test homepage cards drill into same object/detail API, source/dataset badges persistent, counts match response, manual source never relabeled API.

```tsx
it('keeps a conflicted shipment draft while reading the full handbook', async () => {
  const view = await workflowView({initial: 'delivery', conflictOnSubmit: true});
  await view.selectUnits(['CAM-001', 'CAM-002']);
  await view.click('提交发运');
  expect(view.alert()).toContain('版本');
  await view.click('制造手册');
  expect(view.handbookText()).toContain('大制造数字化系统手册');
  await view.click('返回工作');
  expect(view.selectedUnits()).toEqual(['CAM-001', 'CAM-002']);
});
```

- [ ] Add `workflowView` test helper inside `webui/src/workflow/testHelpers.tsx` using React DOM test utilities/Vitest and typed fetch fixtures, not browser driver; include explicit measurements/route fields. Run `npm --prefix webui test -- src/workflow/workspace.test.tsx src/workflow/navigation.test.tsx src/workflow/trace.test.tsx`, initial failure must show unimplemented path.
- [ ] Integrate navigation: 工作台、制造项目、订单与交付、计划与物料、工单与执行、质量与追溯、事项、系统协同、制造手册. Keep old project/legacy entry only for legacy_access. New task center lists owned exceptions/required acceptance issues/readiness blockers and links exact objects; system collaboration shows exchanges/differences, old collaboration accessible only to legacy users. Implement project.stage with real blockers; phase complete cannot make an unshipped order fulfilled. Show original/current promises, actual remaining quantities, immutable version links, real evidence and history on every detail.
- [ ] Finish dirty CAS conflict flow: failed submit retains inputs and operation ID; reload makes explicit choice, replay same operation id only for same payload; edited payload uses new operation ID. Handbook opens without destroying form/scroll; leaving requires one deferred action, onDirtyChange(false) before host external navigation. Revocation clears sensitive data and retires old callback responses. No new auth-error callback can run after unmount.
- [ ] Run targeted UI tests, existing App/index/handbook tests, and `npm --prefix webui run build`. Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_progress.py -q`. Commit `feat: integrate complete daily manufacturing workspaces`.

## Task D2: Reproducible scenario harness and immutable evidence

**Files:** Create MF `tests/workflow/{scenarios/__init__.py,scenarios/base.py,scenarios/fixtures.py,scenarios/full_flows.py,scenarios/exceptions.py,test_acceptance.py,http_app.py,test_restart.py,test_dataset_isolation.py}` and `scripts/run_workflow_acceptance.py`; create `docs/testing/manufacturing-full-workflow-runbook.md`. Extend PF `backend/tests/test_manufacturing_workflow_bridge.py` for real package and identity middleware.

**Interfaces:** `ScenarioContext(run_id,case_id,seed,clock,client,paths,evidence)`; `run_case(context, steps:Sequence[ScenarioStep]|None=None)->CaseResult` (explicit steps only for runner unit tests; CLI uses the registered business scenario); `CaseResult(id,status:'passed'|'failed'|'blocked'|'not_executed',duration_ms,expected,actual,operation_ids,object_ids,artifact_paths,error)`. `EvidenceWriter.record_request/record_response/record_db_snapshot/record_authority_snapshot/finish` writes append-only case artifacts with redacted credentials. Harness has no step named force_success/complete_phase bypassing business. `http_app.py` is test-only and must not be exported in production wheel or host loader.

- [ ] Write runner tests: select known case id, unknown id fails before state; one failing step stops that case and preserves files; next case uses different directory; run manifest includes both git SHAs, tree dirtiness, release hash, seed version, business clock, dataset ID/mode, auth fixture boundary and authority fault config. Replay different seeds generates different UUIDs/SNs but same invariants. `--resume` creates a new run linked to previous failure, never overwrites it.

```python
def test_runner_stops_at_first_error_and_preserves_evidence(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id='E21', seed=41)
    visited = []
    def first(ctx):
        visited.append('first')
        raise AssertionError('intentional quantity mismatch')
    def second(ctx):
        visited.append('second')
    result = run_case(context, steps=[first, second])
    assert result.status == 'failed'
    assert result.error == 'intentional quantity mismatch'
    assert visited == ['first']
    evidence = context.directory / 'result.json'
    original = evidence.read_bytes()
    with pytest.raises(FileExistsError):
        run_case(context, steps=[second])
    assert evidence.read_bytes() == original


def test_runner_records_success_in_a_different_owned_run(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id='E21', seed=42)
    visited = []
    def complete(ctx):
        visited.append('complete')
    result = run_case(context, steps=[complete])
    assert result.status == 'passed'
    assert result.error is None
    assert visited == ['complete']
    manifest = json.loads((context.directory / 'manifest.json').read_text())
    assert manifest['dataset_mode'] == 'test'
    assert manifest['source']['manufacturing_commit']
```

- [ ] Define `ScenarioContext.isolated` constructor and wire actual scenario registry before the above test. Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_acceptance.py tests/workflow/test_dataset_isolation.py -q`, verify failures before implementation.
- [ ] Implement each prerequisite through business HTTP commands with trusted actor cookie, CSRF and qualification checks. PF bridge integration test uses real MF source via TEST_MANUFACTURING_RELEASE_ROOT and host middleware. Standalone harness authenticates synthetic users at a test-only boundary using server-side session map and CSRF tokens; it never adds body/header identity bypass to production router. External state seeds and fault toggles call mock boundary only. Snapshot DBs read-only after actions; compare SQL facts/foreign links/immutable failures to API/dashboard to detect shallow success.
- [ ] Implement script CLI `--cases all|F01,F02|E10,E26 --seed <int> --output <absolute-dir> --business-clock 2026-10-28T00:00:00Z`; one case per child directory with isolated workflow/authority DBs; stop first failing action per case, report all requested case results. Exit0 only if all requested passed; exit1 for failed/blocked; exit2 malformed args. Preserve failures and rerun only impacted cases in a new run. No reset endpoint: CLI deletion refuses anything without matching owned run manifest and explicit test/demo mode; default new directory is safer.
- [ ] Run harness unit tests and a first small F01 smoke; actual full36 execution is D4. Commit `test: add isolated workflow acceptance and evidence harness`.

## Task D3: Real process restart, authorization and legacy preservation

**Files:** Implement `tests/workflow/{http_app.py,test_restart.py,test_dataset_isolation.py}`; extend PF `backend/tests/test_manufacturing_workflow_bridge.py` and MF `tests/workflow/test_identity_store.py`. Add `docs/testing/manufacturing-full-workflow-runbook.md` process and identity boundaries.

**Interfaces:** Test process launch accepts only explicit dataset paths/seed fixture config through local env, binds127.0.0.1 ephemeral port, fixture sessions from a temporary secret file. It must reject production mode and non-temporary ownership manifest. Child uses real workflow router/identity callback and real stateful adapter; termination kills only PID created by test.

- [ ] Write restart E31 at: pending order/grant, after authority commit before platform receipt, after first article, after shipment60 before acceptance. Parent stores IDs/session fixtures, terminates child process, starts fresh process over same DBs, logs in again, reads state via HTTP, queries unresolved receipt and continues. Verify exact output counts/audit/source before/after, no second authority operation. Include two concurrent project edits and authority reservation threads. Existing user session revoked returns401/403, stale response callback cannot reveal new data.

```python
def test_restart_after_external_commit_does_not_duplicate(process_workflow):
    p, exchange = process_workflow.pending_reservation(timeout_after_commit=True)
    process_workflow.restart_and_login()
    result = process_workflow.query_exchange(p['id'], exchange['id'])
    assert result['phase'] == 'accepted'
    assert process_workflow.authority_count(exchange['business_key']) == 1
    assert process_workflow.dashboard(p['id'])['reserved_quantity'] == '80'
```

- [ ] Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_restart.py -q` with existing PF Python environment (uvicorn installed), expect missing process harness failure first; no skip allowed for E31 final gate. Implement bounded startup polling with readiness and child stderr capture; fail on timeout, do not repeatedly restart to pass.
- [ ] Verify E29 real host matrix: unauthenticated, outsider, member own project, member other project/customer, manufacturing-only actor without quality qualification, admin without quality, management_viewer grant writes, revoked grant, hard stale, invalid Origin/CSRF, forged frontend role/header, wrong method/unknown template, old/new source and enabled/disabled/unavailable bootstrap. Confirm old endpoints retain previous admin policy and new members can reach actual shell/assets/CSP/handbook. Use read-only fixture real package; do not declare all members allowed to all old routes.
- [ ] Verify E32 against a seeded legacy fixture containing seven existing projects and representative legacy controls: hash/row count before/after domain scenario and reset; ensure identical. Run alternate seed, altered mock stock, independent databases, foreign dataset path rejection; create sentinel file outside test root and ensure reset refuses it. Verify no production env/real path in test process configuration and UI ongoing simulation label.
- [ ] Run targeted process/host/isolation tests once after fix, record durations and commits. Commit `test: verify workflow restart authorization and dataset boundaries`.

## Task D4: Execute all36, review candidate and record truthful release state

**Files:** Update `docs/testing/manufacturing-full-workflow-acceptance.md` with links to actual results (retain original test requirements); create `docs/testing/manufacturing-full-workflow-results-<run-id>.md`, update `docs/manufacturing-workbench-product-design.md` with achieved architecture/UI boundaries, update existing current architecture/workflow docs where execution meaning changed. Never replace or truncate `docs/manufacturing-system-handbook.md`. Save root `.superpowers/sdd/` verification ledger. Runtime evidence stays outside Git except concise report/redacted manifest.

**Interfaces:** Each matrix row below maps to real test function `test_<ID_lower>()` in `tests/workflow/test_acceptance.py` calling the matching ScenarioRegistry entry. Four full flows live in scenarios/full_flows.py; exceptions in scenarios/exceptions.py. API tests in A/B/C may run many assertions, but final report counts exactly36 scenario results.

| Case | Implementation tasks | Required end-state/evidence beyond status text |
| --- | --- | --- |
| F01 | A1–A4,B1–B3,C1–C3,D1–D3 | Camera100; orders→WO60+40; fixed versions; each SN/lot/test/release; two shipments/acceptances; remaining40 after first; cost/quality close; feedback link retained |
| F02 | A2–A3,B3–B4,C1–C3 | Camera20; trial5 M1 issues; approved ECO M2 subsequent15; both histories; real first article and calibration; deliver/accept/review |
| F03 | A2–A3,B1–B3,C1–C3 | Printer10 WO6+4; distinct printer route/limits; camera evidence rejected; two deliveries/acceptances and closure/feedback |
| F04 | A1–A3,B1–B4,C1–C3 | OEM30 C1/M1; mixed owned supply; customer version approval and release; shipments10+20; customer material consumption/return reconciliation and independent closures |
| E01 | A2,A3 | Forecast rejected for production; later firm demand/source review/order; duplicate ERP source once |
| E02 | A2,B4 | Original promise retained; reduction/cancel pending against allocation/PO/WIP; no silent release |
| E03 | A3,C1 | Wrong customer revision retained as exception; correct one satisfies only matching approval; others independent |
| E04 | B4 | Old/new WO/SN histories and stock/WIP impacts; unresolved disposition prevents ECO close |
| E05 | B1,B2 | Qualified80, in-transit20, confirmed reserve≤80, shortage20 |
| E06 | B1,B2 | Received20, IQC15/5, shortage5 then replacement5; original reject persists |
| E07 | B1,B2 | Foreign owner/frozen/expired/allocated stock rejected; eligible balances unchanged |
| E08 | B1 | Partial receipt sums/balance, original/revised promise, customer replenishment, no duplication |
| E09 | B1,B2 | Unit/precision/cutoff/import errors identify source fields; no readiness success |
| E10 | B2 | Concurrent external atomic reserve sum≤stock; independent receipts and idempotent retry |
| E11 | A3,B4 | New current package never mutates bound executed snapshot; explicit split/switch |
| E12 | A3,B3 | Calibration expired at planned use blocks; corrected evidence and re-evaluation required |
| E13 | B3,C1 | Trial valid without first article; bulk fails for planned/failed first article; genuine retest unblocks |
| E14 | B3 | Wrong station/program/unknownSN/duplicate/overreport no good-count pollution |
| E15 | B3 | Shortage interruption links supply exception; restored stock+plan+resume receipt; timeline retained |
| E16 | C1,C2 | First96/final99/scrap1; four first failures retained; ship100 rejected |
| E17 | C1 | Missing measurement/unit/limit/version not PASS; cannot weaken frozen limits |
| E18 | A1,C1 | Production and bare admin quality403; qualified scoped quality actor approved/audited |
| E19 | C1,C2 | Manufacturing+quality do not replace contractual customer release; shipment blocked until correct receipt |
| E20 | C3,B2 | Lot forward and shippedSN reverse exact links; pending vs accepted freeze, no source impersonation |
| E21 | C2 |60 shipped→40 remaining; duplicateSN/41 rejected; valid40 and acceptance close |
| E22 | C2 | Shipped/signed/accepted separate; required issue has owner and blocks fulfillment |
| E23 | C2,C3 | ERP cost close while quality/RMA unresolved remains open |
| E24 | C3,B4 | RMA→containment→root cause→correction→effectiveness→actual ECO execution; original delivery/history retained |
| E25 | A1,B2 | Same op/payload returns same result once; changed payload409; revoked actor cannot replay |
| E26 | B2,D3 | Authority committed timeout; unknown local status; receipt query resolves once after restart |
| E27 | B2,C3 | Old freeze/unfreeze/version event rejected, current state and rejection audit intact |
| E28 | B2 | Same sum/different detail detected, owned discrepancy; reject never posted |
| E29 | A1,D3 | Real trusted identity/CSRF/project/customer/action ACL and revocation; legacy endpoints protected |
| E30 | A4,D1 | Two edits CAS; draft retained; handbook full/context stable; abandon executes exactly one departure |
| E31 | A1,B2,D3 | Fresh process/session resumes all key states; API/DB/dashboard same; no duplicate operation |
| E32 | A1,D2,D3 | Alternate seeds/reset/mock state; owned test data only, legacy seven unchanged, simulation labels |

- [ ] Execute fresh `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python scripts/run_workflow_acceptance.py --cases all --seed 20261028 --business-clock 2026-10-28T00:00:00Z --output /tmp/manufacturing-workflow-20261028-<run-id>` using existing test Python. Do not retry failing actions inside the case. Record passed/failed/blocked/not_executed summing36. Fix concrete failed requirements, retain first artifacts, rerun affected IDs in a new output directory. Final merged report references each case's exact tested commit; if later changes touch its behavior rerun that case.
- [ ] Run final MF workflow+legacy Python tests, frontend component suite and bundle checks once. Run PF manufacturing bridge/authorization/frontend host/navigation tests with actual built MF source via `TEST_MANUFACTURING_RELEASE_ROOT=<MF-worktree>`; package-enable bridge skips must be eliminated. Unrelated baseline skips remain separately documented, never counted as accepted cases. Commands and environment paths are recorded in runbook.
- [ ] Inspect Git diff/status for both repos, build outputs and exclusions; request spec review and code review under root SDD workflow. Review accesses/transactions/quantity boundaries, undefined UI navigation, missing acceptance assertions and legacy regressions. Fix findings and rerun affected tests; repeat broader suites only when changes warrant.
- [ ] Produce candidate report: exact MF/PF source SHAs, build hash, tests/durations, 36-case manifest, grant/mock boundaries, preserved legacy count/hash, unresolved issues, actual browser/real-system/production status. Fresh read-only runtime baseline must identify deployed source/image/mounts/schema/config, especially Office deployment changes; compare baseline to candidate configuration delta separately. Do not infer deployment from Git merge, existing DB migration, or HTTP200. Production promotion follows root's explicit authorized deployment process; this plan does not request an additional user checkpoint or perform deployment.
- [ ] Commit report and current product docs with `docs: record manufacturing workflow acceptance and candidate evidence`. Root continues any authorized integration/release work. Whole workflow can be claimed implemented/mock-accepted only with all36 passed; otherwise accurately state failures/blockers/unexecuted and continue fixing within scope. Browser visuals and real external/production business acceptance remain separately unexecuted unless actual evidence exists.
