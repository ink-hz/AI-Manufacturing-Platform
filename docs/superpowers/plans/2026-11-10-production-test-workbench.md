# Production Test Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user authorized development; execute continuously without another execution-choice prompt.

**Goal:** Replace the production tools query tabs with the approved role-based dashboards and a real persisted investigation/handoff journey.

**Architecture:** Reuse native read-only SQL transports and the protected workflow router. Add bounded server-side analytics and an isolated SQLite investigation store; browser pages share typed context and selected investigation objects. Integrate exact routes into the platform host, preserving source authorization and all existing manufacturing behavior.

**Tech Stack:** Python 3.11, FastAPI/Pydantic 2, SQLite, React 19, TypeScript, Vitest, existing native MySQL/QuestDB/OSS readers.

## Global Constraints

- Approved specification: `docs/superpowers/specs/2026-11-10-production-test-workbench-product-design.md` at `09a8e8d`. It is the acceptance contract, including its three review amendments.
- Worktree: `/Users/neo/.codex/worktrees/6f75/AI-Manufacturing-Platform`, branch `codex/production-test-workbench`, start `09a8e8d`. Never alter the user's unrelated root documentation/materials.
- The host mainline is `master` at `/Users/neo/Developer/work/AI-Agent-Platform/.worktrees/admin-home-20261109`, initially `57060de1`; the platform root is an old feature branch and is not the integration baseline.
- 首期继续只允许当前平台管理员访问。Read-only admins may read but cannot save/fork/generate handoffs. Recheck actor authorization and source fingerprints for every request.
- 源系统业务写入为0。No external messages, live deployment, source initialization, SQL migrations, or new ordinary-user authorization.
- Native config protocol stays 2 and `build_native_config(config_path, snapshot_path)` remains two-argument compatible. Existing five positional `ProductionToolsConfig` fields remain compatible.
- Each source interval is timezone-aware, half-open, positive, and at most 31 days. Source IDs remain 1–20 digit decimal strings in public JSON/TypeScript. Preserve integer precision and repeated source events.
- Existing source captures remain at most 1000 rows/2 MiB, 24-hour expiry, 100 unexpired captures/project. Analytics must aggregate in SQL, not compute totals from captured rows. Dashboard refreshes must not create observation snapshots.
- Main event: 0 or 1. Comparison: 0 or 1, requires main. Log references: at most 5. Drafts expire 30 days after successful modification; immutable handoffs 30 days after creation. Retain only allowlisted event descriptors, original snapshot positions and canonical content fingerprints, never complete dynamic rows/config contents/object URLs/files.
- Individual drafts are owner-private. Handoffs are read-only to currently authorized admins with matching source fingerprints; continuing creates an owner-private fork. Revoked admins and ordinary users cannot use restore links as capabilities.
- Keep three main boards: 运行总览、测试异常、上位机活动. Tools/config browsing is secondary; version-combination engineering board remains later scope. Shared investigation pages and restorable handoff are first-release scope.
- No invented FPY/OEE, production quantities, device online/offline, permanent source event IDs, final quality state, automatic root causes, or source log one-to-one identity.
- Frontend preserves question time/context on drill/back, expands SN history beyond error/status/device/tool filters, and treats unknown/empty/error/partial/expired distinctly.
- Browser/page acceptance is user-owned per platform `AGENTS.md`; use components, real local HTTP and bounded source checks. Do not autonomously open browsers or deploy.
- TDD for functional changes; each task report records RED, GREEN, commands, warnings/skips and commits. Ledger: `.superpowers/sdd/production-workbench-20261110/progress.md`.

## Task 1: Persisted investigation and immutable handoff HTTP contract

**Files:** Create `production_tools/investigation_models.py`, `investigation_store.py`, `investigations.py`, `investigation_statistics.py`, `investigation_api.py` under `src/manufacturing_platform/`; modify `production_tools/contracts.py`, `service.py`, `transports.py`, `workflow/api.py` only for store configuration and route wiring. Tests: `tests/production_tools/test_investigations.py`, `test_investigation_api.py`.

**Interfaces:** Register protected routes beneath `/production-tools`; use an `InvestigationService(production_service, *, path, clock)` and `register_investigation_routes(router, service, actor)`. Derive the independent path as `snapshot_path + '.investigations.sqlite3'`; validate it against snapshot/config/domain/authority paths and aliases without altering snapshot schema. The optional new path configuration must not break existing factory callers.

Routes and public contracts (all UUID identifiers except decimal source project/log IDs):

```text
GET  /projects/{source_project_id}/investigations -> {items: Draft[], has_more: bool}
POST /projects/{source_project_id}/investigations -> Draft
GET  /projects/{source_project_id}/investigations/{investigation_id} -> Draft
PUT  /projects/{source_project_id}/investigations/{investigation_id} -> Draft
GET  /projects/{source_project_id}/investigations/{investigation_id}/resolve -> Resolution
POST /projects/{source_project_id}/investigations/{investigation_id}/handoffs -> Handoff
GET  /handoffs/{handoff_id} -> Handoff
GET  /handoffs/{handoff_id}/resolve -> Resolution
POST /handoffs/{handoff_id}/fork -> Draft

Draft: {id, source_namespace, source_project_id, owner_id, version,
        created_at, updated_at, expires_at, origin_handoff_id,
        context, primary, comparison, logs, note, impact}
context: {start,end,view,stage_id?,software_id?,software_version?,config_log_id?,
          config_version?,device?,error_code?,order_id?,barcode?,sn?,status?,
          symptom?,candidate_csn?,history_range?,evidence_range?,recent_range?}
Selection input: {snapshot_id: UUID, offset: nonnegative integer}
Selection saved: {selection_id, snapshot_id, offset, source_kind, descriptor,
                  fingerprint, fingerprint_version: 1, captured_at, filters}
PUT: {expected_version, context?,primary?:Selection|null,comparison?:Selection|null,
      logs?:decimal-string[],note?}; omitted fields stay unchanged.
Handoff POST: {expected_version}; Handoff: {id, investigation_id, version,
 created_at,expires_at,context,primary,comparison,logs,note,impact,source_project_id,...}
Fork POST: {}; server supplies fresh owner, UUID and version 1.
Resolution: {primary:Resolved|null,comparison:Resolved|null,logs:[...],captured_at}
Resolved: {state:'verified'|'ambiguous'|'changed'|'not_found'|'partial'|'unavailable',
 descriptor, candidates:[{snapshot_id,offset,row}],complete,error?}
```

Bound and strictly validate bodies/context/notes, reject unknown fields, unsafe payloads and contradictory scopes. Server resolves selections from authorized immutable snapshots; browsers cannot submit trusted descriptors or fingerprints. PUT has optimistic version conflict 409, ownership 404, expiry 410, invalid limits/scopes 422, source/store unavailable sanitized 503. Avoid leaking private connection details through the workflow's traceback boundary.

Task1 review clarified two previously underspecified contracts. Optional `candidate_csn` is an explicit log-search identity; event `sn` must never populate it automatically. Persist exact native descriptors (`workstagesid`, `softwareid`, `version`, `configlogsid`, `cversion`, `workselectid`) and log metadata (`toolsname`, `state`), with corresponding scope validation aliases.

Typed `impact` is server-derived, not a client input: capture counts, filtering definition, read times and coverage on create or context scope changes; retain them for note/selection-only saves and freeze them in handoffs. Use bounded trusted statistics source queries without observation snapshot writes. Baseline denominator excludes result/error-only filters; selected scope and FAIL-only distinct SN use their own explicit filters. Unavailable/unsupported scopes are explicit, never a silently broadened query. Raw observation rows remain absent from durable storage. Task2 must verify newly supported drill filters also flow into impact capture. New async body handlers offload synchronous service operations; strict time input requires explicit ISO date/time plus timezone.

- [ ] Write HTTP tests for admin A draft save/read, admin B denial, readonly/ordinary denial before source I/O, optimistic conflict, 1/1/5 selections and allowed missing main, scope replacement safeguards, metadata-only persistence, reopening a service, 30-day expiration and source-fingerprint changes. A selection of the same main during note updates must preserve comparison/logs; replacing main explicitly clears dependent selections.

```python
def test_draft_is_private_but_frozen_handoff_can_be_forked_by_admin(workflow):
    configure(workflow)
    root = '/api/v1/manufacturing/workflow/production-tools'
    path = root + '/projects/1/investigations'
    draft = workflow.client('admin').post(path, json={
        'context': {'start':'2026-11-09T00:00:00Z',
                    'end':'2026-11-10T00:00:00Z','view':'anomalies'},
        'note':'Investigate the selected time range',
    })
    assert draft.status_code == 200, draft.text
    identifier = draft.json()['id']
    assert workflow.client('owner').get(path+'/'+identifier).status_code == 404
    handoff = workflow.client('admin').post(path+'/'+identifier+'/handoffs',
        json={'expected_version':draft.json()['version']})
    assert handoff.status_code == 200, handoff.text
    assert workflow.client('owner').get(root+'/handoffs/'+handoff.json()['id']).status_code == 200
```

- [ ] Run `PYTHONPATH=src python3.11 -m pytest -q tests/production_tools/test_investigations.py tests/production_tools/test_investigation_api.py` and capture expected missing-route/module failure.
- [ ] Implement store/models/service/routes. Resolve expired snapshots using exact event time and SN in bounded source queries, retaining all ambiguous duplicates and source content changes; never select the first candidate automatically. Reuse existing `ProductionQuery` fields now; Task 2 extends filters. Log revalidation must use current project membership/existence and allowlisted metadata, not supplied URLs.
- [ ] Rerun new tests and `tests/production_tools/test_snapshots.py tests/production_tools/test_api.py tests/production_tools/test_standalone.py`; verify source snapshots retain schema/version/TTL/limits.
- [ ] Commit task and write `.superpowers/sdd/production-workbench-20261110/task-1-report.md`; task review before next task.

## Task 2: Native analytics and complete drill filters

**Files:** Create `production_tools/analytics.py`, `analytics_queries.py`, `analytics_api.py`; extend `contracts.py`, `queries.py`, `source.py`, `service.py`, `api.py`, `workflow/api.py`. Tests: `test_analytics.py`, `test_analytics_api.py`, extend `test_queries.py` and exact route inventories as needed.

**Interfaces:** Keep `SourceKind` unchanged. Add typed analytics filters, fixed SQL registry and `NativeProductionSource.analysis(scope, filters, view)`; service exposes project analyses and server-side paged overview. Register:

```text
GET /production-tools/overview?start,end,before_id? -> Overview
GET /production-tools/projects/{id}/analysis?view,start,end,...filters -> Analysis
GET /production-tools/projects/{id}/availability -> {source_namespace,
 source_project_id,captured_at,latest_at:string|null}
view = summary | stages | errors | devices | activity | trend | versions
Analysis: {view, source_namespace,source_project_id,captured_at,filters,
           items:Aggregate[], complete,truncation_reason,bucket_minutes?}
Aggregate: {key, stage_id?,software_id?,device?,error_code?,software_version?,
 config_log_id?,config_version?,timestamp?,records,distinct_sn,pass_records,
 fail_records,unknown_records,failed_sn,first_time?,last_time?,denominator_records?}
Overview: {items:[{id,name,state:'ready'|'unavailable',statistics:Aggregate|null,
 trend:Aggregate[],latest_at:string|null}],captured_at,complete,
 limit:100,has_more,next_before_id,source_namespace}
```

Extend observation/statistics filters with `stage_id,software_id,software_version,config_log_id,config_version,error_code,barcode`; preserve old SQL templates for unchanged filters and exact IDs. Evidence adds supported device and tool-name filters. Use fixed source field mapping (`workstagesid`, `softwareid`, `version`, `configlogsid`, `cversion`, `errorcode`, `barcode`); no arbitrary client SQL identifiers.

Review-required exact unknown-group support: add optional `missing_fields` finite list for stage_id/software_id/config_log_id/software_version/config_version/device/error_code. HTTP encodes it as one comma-separated value; investigation JSON uses a list. Reject duplicates, unknown fields and simultaneous exact/missing predicates for the same dimension. SQL missing predicates share the grouping definition (ID NULL/empty/0/-1; text NULL/empty). Carry this scope through observations/statistics/analysis, saved investigation/impact, selection checks and restore. Remove only the missing error_code symptom from baselines, retaining missing device/stage/etc. Do not silently broaden or disable the approved missing-device record journey. Evidence accepts only its valid missing dimensions and keeps event/log identities independent.

Overview statistics/trend/latest have independent explicit state/readtime/coverage; a later block error never clears earlier successful blocks. Any gap makes whole-response complete false. UI must distinguish successful empty trend/history from unavailable or truncated data. Add first_time as SQL MIN(timestamp) for the chosen scope so range-local first occurrence is source-derived, never inferred from captured rows.

Aggregates execute over the full source interval. Bound result groups to 1000 with sentinel and explicit partial state, preserve huge counts as exact public strings. Time buckets chosen from fixed minute values 5/15/30/60/180/360/720/1440 so no more than 96 buckets per scope. Overview obtains at most one directory page server-side, reports its coverage and computes source aggregates without browser fanout; group source queries by this bounded directory where practical. Do not show an all-project total for an incomplete page. No analysis refresh writes source snapshots or consumes their 100-count quota. Default records are production only; stopover is separate on SN history.

Availability is a single-row fixed metadata SELECT of the latest actual production timestamp for the authorized project, independent of the chosen observation interval; it does not retrieve raw history or pretend to report ingestion/heartbeat state. It enables an explicit jump to a historical data window when today's results are empty. Keep existing transport timeouts/slots and sanitized errors. Cache immutable approved SQL-shape sets when extending legacy filter combinations rather than rebuilding thousands of templates per request.

Errors use FAIL records grouped by project/stage/tool/code, retaining missing codes. Denominator excludes symptom/result-only restrictions but retains base scope. `failed_sn` counts unique nonempty SN with FAIL, not repeated records. Status unknown remains a separate count. Cross-group distinct counts must never be summed into a fake whole-project count. Dynamic item analytics only for actually validated profiles; otherwise omit the mode instead of inferring FAIL from arbitrary columns. Lookup names with fixed bounded dictionary reads where available, retain IDs with clear unknown labels when mapping absent.

- [ ] Write query and HTTP tests proving grouping sees rows beyond 1000, duplicate SN behavior, partial groups, source unavailable vs zero, denominator after error/status selection, SQL registry/injection rejection, decimal IDs and large counts, short/31-day bucket limits, no snapshot-quota consumption, unauthorized zero-I/O.

```python
def test_server_aggregate_is_not_the_bounded_observation_sample(workflow):
    client, reader = install_analytics_source(workflow, records=2500, failed_sn=12)
    response = client.get(BASE+'/projects/1/analysis', params={
        'view':'summary','start':'2026-11-09T00:00:00Z',
        'end':'2026-11-10T00:00:00Z'})
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['records'] == 2500
    assert response.json()['items'][0]['failed_sn'] == 12
    assert reader.used_aggregate_sql
```

- [ ] Record RED via `PYTHONPATH=src python3.11 -m pytest -q tests/production_tools/test_analytics.py tests/production_tools/test_analytics_api.py`.
- [ ] Implement registered parameterized SELECTs and bounded normalization/errors, endpoint wiring and exact typed filtering; no source writes or fake totals.
- [ ] Verify investigation `impact` uses every newly supported scope field and preserves error/result-free denominators, failure-involved SN and immutable handoff values after source/context changes. Never treat unsupported statistical filters as permission to drop them.
- [ ] Rerun new tests plus native query/source/transports/precision/API suites; commit and report Task 2, then task review.

## Task 3: Role-based React workbench and shared investigation journeys

**Files:** Replace `ProductionToolsWorkspace.tsx`, `productionTools.css`; extend `types.ts`, `workflow/api.ts`, `WorkflowApp.tsx`; add focused `boards.tsx`, `details.tsx`, `investigations.tsx`, `context.ts`, `productionApi.ts` as needed to keep responsibilities small. Replace old workspace tests with journey tests; retain cancellation/precision/boundary regression behavior in the new UI.

**Interfaces:** Use Task 1/2 endpoints and exact public names. Existing `createWorkflowApi` methods stay compatible; add methods `productionOverview`, `productionAnalysis`, investigation CRUD/resolve/handoff/fork. Request helper handles CSRF, cancellation and auth loss; service/host enforce read-only, and the workspace receives explicit readOnly/userId props from bootstrap to disable mutations and scope resume state. Support an internal URL query parameter `production_handoff=<UUID>` for authenticated restore links; consume it only inside production module, and allow entering the handoff ID directly. Do not embed raw event data in URLs.

The shell must select the production module for a valid restore parameter after access checks; otherwise the workspace would never mount when opening a copied link from the home page. Non-admins still cannot enter or read the handoff. Restore saved metadata independently of live directory loading, so an unavailable source project directory does not hide an otherwise authorized stored handoff.

Three main nav buttons, project details before records, anomaly master/detail with scope chips and denominators, activity time grid and explicit near-now comparison, shared SN full page and event sidebar. Source/context names are readable, timestamps local with timezone, PASS/FAIL/unknown explicit. No raw JSON as main detail, no parent-ID entry, no speculative graph/KPI placeholders. Secondary tool/config catalog uses object clicks for versions. Search records and SN shortcuts allow direct entry.

Use `missing_fields` for exact nullable-group drills, preserve those visible scope chips through save/restore and denominator queries. Read overview block-specific states so a failed trend/latest block does not hide valid counts or paint unknown time buckets as zero. Use source first_time/last_time for range-local occurrence labels. Event SN must not prefill candidate log CSN.

Current draft state: explicit main/comparison selection, 5 log references, server autosave with visible state/version, owner-private resume list, project detach/rejoin and refresh restore via stored draft ID, conflict protection. Generate immutable handoff only after successful save; receivers see saved context then resolve candidates/fork. Do not claim a historical row was restored without verification. Readonly admins can read, cannot save/generate/fork.

- [ ] Write component journey tests with real API-shaped fetch fixtures: manager overview -> project/stage -> anomaly; selected error -> SN history showing previous PASS on other device/tool; event selection and comparison save survive project switch and remount; admin receiver restore -> expired candidate verification -> fork; failed save blocks handoff; near-now view preserves problem range; partial/error/unknown/no-source states and large decimal IDs.

```tsx
it('opens project explanation before records and keeps investigation time on drill', async () => {
  const v = await renderProductionWorkbench(realApiFixture());
  await v.click('查看项目 A');
  expect(v.host.textContent).toContain('测试环节');
  await v.click('查看该范围异常');
  expect(v.latestAnalysisQuery().start).toBe(v.originalRange.start);
  await v.click('查看 SN-A 履历');
  expect(v.host.textContent).toContain('通过');
  expect(v.latestObservationsQuery().status).toBeUndefined();
});
```

- [ ] Record missing/new behavior failures with `npm test -- src/workflow/productionTools`.
- [ ] Implement the workbench with scoped async cancellation, shared history/context and persisted investigation controls; no changes to unrelated manufacturing workflows.
- [ ] Run relevant frontend API/navigation/journey tests, `npm run test:bundle`, then broader existing frontend once. Report any inherited warnings exactly. Commit Task 3 and task review.


## Task3 review architecture correction

The first independent review exposed multiple symptoms from shared responsibilities, rather than unrelated rendering defects. Display/navigation scope, persisted investigation scope and asynchronous verification ownership must be separate:

- Navigation/back changes the displayed page and restores its local filters/position; it cannot silently rewrite an existing range investigation. Explicit filter edits and starting/replacing investigation scope use deliberate persistence actions, retaining main/dependency safeguards. The global overview exposes only scope actually used by its API; prior investigation scope stays available on return. Default live overview advances its end time, while historical selections and investigations stay fixed.
- Every resolve/candidate result belongs to current account, project, draft/handoff identity/version and selections. A new main/comparison clears stale verified rows immediately; same-project newer resolutions invalidate older requests as well.
- Browser back/forward is a transaction: accepted navigation aligns browser state, visible page and internal index; cancelled leave restores all three consistently.
- Account-scoped resume locators restore the active project/draft/view without requiring project reselection. Failed first creation has no server ID, so its explicit local unsaved-state recovery must work independently of saved-draft IDs. Persist metadata/patches only, never raw observation rows.

Fix all confirmed review findings in one wave, with targeted RED/GREEN for each trigger and a covering API/navigation/production run plus bundle. No ordinary-user access, raw-row persistence, source writes, new query fallbacks or silent scope broadening.

## Task 4: Platform host integration, end-to-end checks and delivery

**Files:** In an isolated platform worktree based on `master`, update only manufacturing exact route registry, optional storage path validation and its integration tests. In MF add HTTP journey tests and `docs/verification/production-test-workbench-2026-11-10.md`, update product spec implementation status accurately.

**Cross-layer correction:** Verify same-stage/tool comparison can retain a different software/config version from the selected symptom. Narrowly adjust comparison context validation (including missing-version scope) without relaxing main/source/project checks; record targeted RED/GREEN. Add optional bounded `context.history_sn` as the independent SN履历 subject, alongside history_range; exclude it from original scope/impact/primary validation and verify persistence/fork round-trip. Add output-only `Resolution.binding={kind,id,version,primary_selection_id,comparison_selection_id}` from the actual resolved payload, so the frontend can reject results for another server revision or selected event; verify both draft and immutable handoff binding through HTTP.

**Interfaces:** Host registry must enumerate every new method/path exactly, including POST/PUT investigation writes and GET analytics; unavailable router retains admin/no-store/read-only semantics. Do not loosen wildcard paths. Reserve unavailable operations by exact method/path so a missing POST or PUT cannot intercept a released GET on the same path; production fallbacks retain administrator checks. Keep optional production failure from disabling other manufacturing routes. Derived investigation DB cannot alias workflow/domain/authority/snapshot/config files, including symlink/hardlink aliases.

- [ ] Add host contract test comparing released router routes to host registry and admin/read-only/ordinary authorization for new endpoints; verify RED before host changes.
- [ ] Integrate exact paths and path isolation. Preserve CSRF/Origin and authenticated real HTTP behavior.
- [ ] Run local real HTTP journey with explicit test identities and isolated native readers: save A -> immutable handoff -> B restore/fork -> expiration/ambiguity -> readonly/ordinary denial. Separately report injected source boundaries; never call this real-source or production acceptance.
- [ ] Run affected MF backend, frontend, platform manufacturing integration and bundle checks once; broaden only on new failures. Run real-source SELECT acceptance if existing authorized private configuration is available, bounded and sanitized; if unavailable record the gap, never substitute demo data.
- [ ] Request final whole-branch review, fix all Critical/Important findings and targeted retests. Merge reviewed MF/PF branches to their current mainlines without touching unrelated work. No deployment in this task. Write exact commits, passed/failed/skipped/unexecuted checks, browser and production gaps, and deliver implementation links.

## Progress

- [x] Task 1 reviewed (`a1102ee`)
- [x] Task 2 reviewed (`83cad73`)
- [x] Task 3 reviewed (`6aef6f5`)
- [ ] Task 4 reviewed and integrated

Plan coverage: role/private-access rules and durable objects are Task 1; native semantics and full-scope boards Task 2; every first-release page and user journey Task 3; actual host authorization and cross-layer delivery Task 4. Version-use board remains explicitly outside first release.
