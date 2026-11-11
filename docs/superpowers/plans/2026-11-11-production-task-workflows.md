# Production task workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver four usable production-test task paths, with strong failure/actual-version drill-down and no development or data-explanation prose in the product.

**Architecture:** Reuse current bounded read-only APIs and investigation contracts. The existing catalog view becomes the tools/versions module: no explicit directory kind means actual version usage, explicit kind means the existing directory. Retain root investigation state and shared detail journeys.

**Tech Stack:** Existing React/TypeScript/CSS/Vitest; no new dependencies or backend changes.

## Global Constraints

- Frontend only. Preserve source queries,21 routes,administrator-only access,backend,persistence formats,dependencies and deployment tools. No changes to src/,deploy/,package manifests or lockfiles.
- Main navigation: 项目总览 / 失败分析 / 现场上位机 / 版本使用. Internal views stay overview/anomalies/activity/catalog. Explicit Location.catalog opens directory; catalog undefined opens version usage.
- No default or expanded explanatory UI about captured/read times,snapshots,source namespaces,fingerprints,schema,protocol,raw backend columns,atomic snapshots or data definitions. Remove 统计说明. Actual event time/filter controls/meaningful handoff references remain.
- Keep exact decimal strings,precise captured time bounds,missing-field predicates,clamped drills,unknown/partial/stale truth and action-oriented errors. No fake test-item analysis,baseline compliance,online/offline/deployment/quality claims.
- Investigation controller stays mounted; preserve autosave/dirty/CAS/fixed handoff/event/log binding and permission guards. Never change outbound persisted structures to simplify presentation.
- Anonymous synthetic fixtures only. No user real source data,names,credentials. No browser automation; other manufacturing modules unchanged.

### Task 1: Actual version usage and task navigation

**Files:** Create `webui/src/workflow/productionTools/VersionUsageBoard.tsx`, `versionUsage.css`, `VersionUsageBoard.test.tsx`; modify `ProductionToolsWorkspace.tsx`, `context.ts` only if necessary for restore reset, `boards.tsx` OverviewBoard chooser region, `ProductionToolsWorkspace.test.tsx`, `boardsContent.test.tsx`, `shell.test.tsx`, `navigation.test.tsx` for affected labels.

**Interfaces:** Consume existing BoardProps,productionAnalysis(view=versions|devices),productionCatalog,drill/baseline/editScope. Export `VersionUsageBoard(props: BoardProps)`. Keep View/InvestigationContext/backend unchanged. Task2 consumes resulting navigation and unchanged board interfaces; Task3 will remove shared process prose.

- [x] Add behavioral tests for a fourth task and chooser, source selection preserving catalog usage vs explicit directory, old directory links, restored version scope, exact huge IDs/missing-version combo drills, filters/stale request isolation and unknown/partial/error states. Representative action assertion: `expect(go.mock.calls[0][0]).toMatchObject({view:"records",projectId:"1",scope:{...scope,software_id:"9007199254740993",software_version:"v2",config_log_id:"9007199254740994",config_version:"7",status:"2"}})`.
- [x] Run new/version and affected Workspace tests from webui, record meaningful RED failures before implementation.
- [x] Implement version table from versions aggregates and bounded optional directory names (no automatic whole-directory scans), compact selected-combination device table and actions 查看测试/查看失败/查看上位机. Distinct missing versions/configs must use drill predicates and not merge. Use captured project/time and no float conversion for IDs/counts. Detail selection may be local, but every outgoing action must include the full selected combo and clear unrelated stale result/error predicates for all-tests reads.
- [x] Wire fourth task to view=catalog,catalog=undefined; directory action sets catalog=software. Keep explicit event directory links. Preserve task on project selection; no-project chooser actions match version usage. Reset transient catalog/parentId when restoring a saved catalog context so stale directory mode cannot override restored version scope.
- [x] Rename only user task labels; retain internal IDs. Do not modify AnomaliesBoard/ActivityBoard bodies or shared Coverage/Counts in this task.
- [x] Run focused affected tests and `npm run test:bundle`, inspect output, commit scoped files; report RED/GREEN,exact commit/tests,files and concerns.

### Task 2: Failure and on-site investigation paths

**Files:** Modify `webui/src/workflow/productionTools/boards.tsx` AnomaliesBoard/ActivityBoard regions, `boards.css`; test `boardsVisual.test.tsx`, `ProductionToolsWorkspace.test.tsx` and new `failureJourneys.test.tsx` where useful.

**Interfaces:** Keep BoardProps,API calls,View and outgoing Location shapes. Task1 fourth navigation/version actions already land on anomalies/activity/device with full combo filters. Shared ReadBlock/Coverage/Counts presentation is Task3 ownership.

- [x] Add tests for compact ranked symptom rows, selected symptom distributions, all-tests baseline, same-code-different-tool selection, missing-device filters, version-to-failure-to-SN flow and PE table-to-device/window drill. Representative assertions: errors read uses `baseline(scope)` while selected groups/records preserve selected symptom; all-tests uses `baseline(scope)`; device detail uses `drill(scope,item,["device"])`.
- [x] Run affected board/journey tests, capture expected RED for changed behavior.
- [x] Replace per-symptom four-metric cards with semantic rank rows showing error/tool-stage/failed SN/failure count/applicable sample. Selected detail uses concise scale and distribution tables with explicit limit/open actions; records are directly reachable. Preserve no-error FAIL groups,sort exact counts and independent errors. Put long trend behind explicit 查看趋势 (mount only when opened), without deleting accessible clamped time drills.
- [x] Replace device metric-card wall with table of machine,test SN,failed SN,test counts,last actual event and action. Keep actual activity grid and detail errors/versions/record action. On device detail, show concise error/version tables and independent 近况 action; preserve original time and96-bucket/unknown/missing semantics. Never claim heartbeat or physical asset identity.
- [x] Update affected meaningful old presentation expectations intentionally; preserve every query,scope,investigation and metadata-race protection. Run focused affected tests and test:bundle once, commit scoped files and report exact RED/GREEN and concerns.

### Task 3: Product copy, details and state presentation

**Files:** Modify `webui/src/workflow/productionTools/boards.tsx` shared primitives/overview/project prose, `charts.tsx`, `details.tsx`, `investigations.tsx`, `productionTools.css`, `details.css` as needed, `context.ts` error text only if needed; affected productionTools tests and a new `productContent.test.tsx` if useful. Do not change API/controller/resolver/persistence/nav semantics.

**Interfaces:** Existing shared Coverage/Counts/ReadBlock exports remain available. Complete Coverage returns null; partial Coverage returns concise actionable status without raw reason codes. All metadata remains in data/controller and outgoing payloads.

- [x] Add focused behavior assertions that a default board/event/catalog/investigation has no statistics help,read/capture trace,snapshot UUID/raw backend column dump; partial and save/restore/conflict errors still visible with actions. Preserve exact snapshot/binding assertions in existing journey tests.
- [x] Run affected tests for meaningful RED before modifying presentation.
- [x] Remove UpdatedAt/StatisticsHelp and successful provenance paragraphs; compact ReadBlock loading/retry/stale and Coverage partial copy. Remove repetitive instructional descriptions from boards/charts while retaining real data labels,axes/legend and missing-state markers. Checkbox becomes 自动刷新; timer behavior unchanged.
- [x] Clean RecordTable/History/Parameters/Compare/EventSidebar: no capture IDs,row offsets/read timestamps or operating instructions in default product; keep actual event times and business measurements,optional raw business record. Catalog switches to a small allowlist of meaningful name/version/details/review-state/author fields, never Object.entries default dump of IDs/internal keys; preserve scoped directory/version navigation and exact query identities.
- [x] Clean InvestigationPanel presentation: business objects,note,save/error/conflict/restore and handoff references remain. Remove source/fingerprint/capture/atomic-snapshot lectures and repeated empty subsections; never modify fixed handoff serialization or evidence identity. Meaningful expiry/object ambiguity notices remain short and actionable.
- [x] Update affected text assertions, keeping original controller/query protections. Run productionTools tests + test:bundle; commit scoped files and report RED/GREEN and exact evidence.

### Task 4: Final integration and authorized release

**Files:** Verification/release docs and plan progress; no backend or release helper code changes.

- [x] Obtain fresh task-scoped reviews after each task and one whole-branch review after all3tasks. Address concrete findings through implementer/fix agent and original reviewer recheck. Preserve first failures and resolve every cross-task check.
- [x] Retain Task2 general frontend evidence (477 passed), then run the affected productionTools/navigation/API/shell checks after Task3 and final fixes; general command: `WORKFLOW_TEST_PYTHON=/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform/.venv/bin/python npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx`; only affected rechecks after fixes. Check source/backend/deploy/dependency trees unchanged.
- [x] Merge/push reviewed code into main while preserving original-root unrelated work. Build from exact committed Git content. Reuse guarded full candidate pipeline, current MFb4b3fc7/PFf8 baseline and66ordered compose inputs;36candidate incl actual E30/OEM and local archive verification remain mandatory before cutover.
- [x] Only API cutover; verify health/assets,21handlers,read-only current source policy,data/source config/SDK/PF/Nginx/other34containers preservation and independent public HTTPS. Record actual deployed app SHA separately from later docs commit. Keep browser acceptance user-owned.
- [x] Commit/push accurate release/verification records and completed plan; retain private first failures,reviews and signed/hashed evidence. Final concise user report names delivered workflows and deployment status without claiming browser acceptance.
