# Production workbench content and task flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the first screen answer which projects have testing and failures, then provide a direct path into analysis without process prose or empty investigation forms.

**Architecture:** Keep all existing API/controller/persistence contracts. Separate workspace presentation and task navigation from data-board presentation; these are independent changes with unchanged BoardProps. Reuse productionOverview to choose projects for a task, without new per-project scans.

**Tech Stack:** Existing React/TypeScript, CSS, Vitest/jsdom, no new dependencies.

## Global Constraints

- Only frontend changes; preserve source queries, 21 routes, administrator-only access, backend, persistence formats and deployment tools.
- Use anonymous synthetic projects in tests; never copy the user's real project names or source rows.
- Keep exact decimal counts, partial/unknown/stale warnings, precise captured time bounds, clamped drills and missing-field semantics.
- Keep the investigation root controller mounted, including dirty/autosave/CAS/fixed-handoff/event/log behavior; presentation may be conditional.
- No browser automation; user owns browser acceptance. Other manufacturing modules remain unchanged.
- UI task labels: 运行总览 / 失败分析 / 上位机活动. Internal view id anomalies remains unchanged. KPI labels: 有测试项目 / 测试次数 / 测试 SN / 失败 SN.
- OverviewBoard keeps BoardProps and derives chooser task from location.view. A selected source project retains anomalies/activity task; overview/project selection may enter project details.
- Remove successful process prose by default; actual read failures, incomplete/unknown data, stale content and display limits remain visible.

### Task 1: Workspace content and progressive investigation

**Files:** Modify `webui/src/workflow/productionTools/ProductionToolsWorkspace.tsx`, `investigations.tsx`, `context.ts`, `productionTools.css`, and the two precision attributes in `details.tsx`; production-only duplicate headings in `webui/src/workflow/WorkflowApp.tsx` and `webui/src/console/ConsoleShell.tsx` if needed. Test `ProductionToolsWorkspace.test.tsx`, `shell.test.tsx`, `detailsVisual.test.tsx` as relevant.

**Interfaces:** Keep BoardProps and all existing controller types. The no-project OverviewBoard reads location.view to show a task chooser. Do not modify boards.tsx/charts.tsx/boards.css or their tests (Task 2 ownership).

- [x] Add behavioral tests to existing React harness. Initial rendering must have no blank investigation form or duplicate nested title/provenance text. Clicking restore must reveal and focus the restore input; a failed linked restore remains visible. Keep existing dirty/conflict/restore interaction assertions.
- [x] Add tests showing source selection retains anomalies/activity, and localInput round-trips nonzero seconds/milliseconds. Example: `expect(new Date(localInput("2026-11-11T01:40:59.123Z")).toISOString()).toBe("2026-11-11T01:40:59.123Z")`.
- [x] Run `npm test -- src/workflow/productionTools/ProductionToolsWorkspace.test.tsx src/workflow/productionTools/shell.test.tsx` from webui; capture expected RED evidence only for new behavior.
- [x] Remove nested h2/eyebrows/intro and the repetitive successful scope paragraph; use compact project/time/apply/refresh controls. Keep one parent title and accessible input names. Set datetime step precision consistently with actual scope, without rounding stored bounds.
- [x] Rename tab text to 失败分析, preserve task on source selection; remove the no-project scanning-process paragraph. Keep mounted controller, condition investigation presentation by explicit open or real state. Restore must open before focus (effect/ref); active errors and conflicts visible. Preserve every business callback and guard.
- [x] If a production-only parent badge/eyebrow is removed, condition it on production view and test other module remains unchanged. Avoid unrelated refactors.
- [x] Run affected component tests once after changes and `npm run test:bundle`; fix actual failures, record exact evidence, commit only owned files, write report including RED/GREEN, commits, changed files and concerns.

### Task 2: Task-oriented project table and legible chart counts

**Files:** Modify `webui/src/workflow/productionTools/boards.tsx`, `charts.tsx`, `boards.css`; test `boardsVisual.test.tsx`, `charts.test.tsx` and a focused new `boardsContent.test.tsx` if needed.

**Interfaces:** Keep BoardProps/exports/service calls. Infer overview chooser task from location.view. Task 1 retains anomalies/activity on selecting a project. Do not modify workspace/controller/context/shared CSS files (Task 1 ownership).

- [x] Add tests with three anonymous active/complete-zero/unavailable projects. Assert active and unknown rows visible, known zero row absent until toggle, no wrong normal status, no initial mini-trends/process text. Check primary failure action `go` has view anomalies, project and exact scope. For activity chooser, assert activity heading/action and preserved view.
- [x] Add a chart assertion using records=100/fail_records=10 in same bucket: failure height must be one tenth of tests with a common denominator; retain large-string exact-value and clamped-drill tests.
- [x] Run `npm test -- src/workflow/productionTools/boardsVisual.test.tsx src/workflow/productionTools/charts.test.tsx src/workflow/productionTools/boardsContent.test.tsx` from webui and record expected RED.
- [x] Render OverviewBoard with four concise KPI labels and a compact semantic table: project, tests, test SN, failed SN, failed tests, last test, action. Active/partial/unavailable stay visible; only complete known zeros enter a collapsed section. Display unavailable counts as dashes. No project mini-chart. Primary CTA opens failures, project name opens details; chooser heading/action follows anomalies/activity.
- [x] Simplify Coverage so full successful read has no paragraph, with concise partial warning. Provide one update time, optional statistics help for record/SN definitions/provenance; no repeated successful read traces. Scope must not be called today for custom ranges. Keep paginated-page limits truthful and do not imply all accessible projects were summed when incomplete.
- [x] Remove verbose process descriptions from Project/Anomalies/Activity boards; keep real unknown/stale/truncation alerts visible. Use 测试次数 / 其中失败 chart labels and shared maximum for both counts, preserving exact decimal values, native button access, missing bucket positions and clamped time bounds.
- [x] Run focused board/chart tests and `npm run test:bundle`; update old label assertions intentionally, without weakening query/partial-state checks. Commit owned files and report RED/GREEN, exact tests, commits, concerns.

### Task 3: Integration, review and release

**Files:** Integration of Tasks 1/2, focused verification/release documentation only.

**Interfaces:** Existing guarded release pipeline; no backend or deployment helper changes.

- [x] Review each task via a fresh task reviewer using a generated diff file and implementer evidence. Resolve Important/Critical findings in a single scoped fix wave and re-review. Combine independent commits without overwriting concurrent user work.
- [x] Run combined productionTools component tests and bundle after integration. Run general frontend regression once for changed shell/navigation, with existing Python3.11 environment and separate E30 candidate verification. Preserve first failures; do not repeat passing unrelated suites.
- [x] Obtain one independent whole-branch review; address any findings and recheck amended behavior. Verify changed-file scope excludes backend/API/persistence/deployment code and real source data.
- [x] Merge reviewed branch into main preserving unrelated dirty SAP files; push. Construct release from exact committed Git content. Execute fresh guarded full 36-test candidate including E30/OEM, archive/hash evidence; only API cutover with full compose inputs after all gates pass.
- [x] Verify production identity, health, complete static bytes, read-only source/admin permissions, unchanged PF/Nginx/other containers/data. Record app SHA separate from later documentation SHA, commit/push release and verification records. Report concise result without claiming user browser acceptance.
