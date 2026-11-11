# Production workbench visual implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the complete production workbench presentation so hierarchy, failures, scope, evidence and available actions are immediately distinguishable.

**Architecture:** A locally scoped visual system provides panels, semantic badges, KPI tiles and display helpers. Boards and investigation/detail surfaces consume it while preserving all source queries, navigation and durable investigation logic. Reuse the existing isolated worktree and locked dependencies.

**Tech Stack:** React19, TypeScript5.6, scoped CSS, native SVG/HTML, Vitest5/jsdom; no new dependencies.

## Global Constraints

- Follow `docs/superpowers/specs/2026-11-11-production-workbench-visual-design.md`.
- Only `webui/src/workflow/productionTools` presentation and task documentation may change. API payloads, authorization, source meanings, navigation/capture binding and persistence behavior stay intact.
- Decimal counts support up to20 digits; normalize with BigInt before conversion to bounded SVG/CSS percentages. Unknown/partial is never zero; zero failures is neutral; no event is not offline or PASS.
- CSS stays inside `.mf-root.wf-root .wf-production-tools[data-pt-workspace]`, with sufficient specificity against host styles and no `!important`. Desktop and760px layouts, focus-visible, reduced-motion and readable overflow must be supported.
- No new packages, browser automation, employee sessions, production writes, publishing, or deployment by task agents. Existing browser acceptance belongs to the user.
- Preserve first failures; run a focused correction batch, not retries until green. Tests assert user-visible meaning and real interactions, not exact CSS file strings.
- Commit only task-owned files; all workers share one worktree. Root coordinates commits/review and records the exact base before each task.

### Task 1: Shared visual system and workspace hierarchy

**Files:** Create `visuals.tsx`, `visuals.test.tsx` and optional `visuals.css` in `webui/src/workflow/productionTools`; modify `productionTools.css`, `ProductionToolsWorkspace.tsx`; add `visualCascade.test.tsx` if needed. Do not edit boards/details/investigations.

**Interfaces:** Export `Tone = 'neutral'|'info'|'success'|'warning'|'danger'`; `Badge({tone,children})`; `Metric({label,value,detail,tone,onClick})` with value `string|null`, detail optional ReactNode and onClick optional callback; `Panel({title,eyebrow,description,actions,children,className})` with optional strings/ReactNode except title/children; `ResultBadge({value})` for actual 1/PASS,2/FAIL,otherwise unknown; `EmptyState({title,description})`. Class prefixes `pt-`; status uses `data-tone`. Export a pure `boundedPercent(value:string,max:string):number` producing0..100 by BigInt arithmetic, validated nonnegative decimal counts; it never parses raw huge counts through Number.

- [ ] Write presentation tests first, including actual output semantics and a mounted host with both workflow.css and productionTools.css so title hierarchy survives the real parent rules. Test zero, null and `99999999999999999999`, visible unknown result, label/value accessibility and clickable KPI action.
- [ ] Run `npm test -- src/workflow/productionTools/visuals.test.tsx src/workflow/productionTools/visualCascade.test.tsx` for the intentional missing-feature failure. Retain this evidence.
- [ ] Implement the interfaces and full scoped design foundation. Workspace gets `data-pt-workspace`, structured heading, grouped navigation, compact action toolbar and range/search panels. Keep existing event handlers, names used by existing tests and unsaved-dialog behavior.
- [ ] Apply panel, metric, badge, chart/table base, section/action variants, focus/responsive primitives to all existing surfaces via scoped CSS. Make generic styles sufficient for later task-specific classes without all-white nested cards.
- [ ] Run the new tests, existing `ProductionToolsWorkspace.test.tsx`/`shell.test.tsx` and `npm run test:bundle`. Fix only actual regressions and report any downstream styling hooks clearly.
- [ ] Commit task-owned files, write `.superpowers/sdd/visual-20261111/task-1-report.md` with red/green evidence, commands, exact results, self-review and commit range.

### Task 2: Three boards, project overview and truthful charts

**Files:** Modify `boards.tsx`; create `charts.tsx`, `boards.css`, `boardsVisual.test.tsx` (and `charts.test.tsx` when useful). Tests may reuse the existing harness without editing unrelated tests. Do not edit workspace/shared primitives/detail/investigation files.

**Interfaces:** Consume Task1 primitives. Preserve `BoardProps`, `ReadBlock`, `Coverage`, `Counts`, `OverviewBoard`, `ProjectBoard`, `AnomaliesBoard`, `ActivityBoard` exports and their exact navigation/query behavior. Reexport if boards are split. `TrendChart({data,scope,onRange})` consumes Analysis/Scope and calls `(scope:Scope)=>void`; chart labels retain exact source counts. Optional `MiniTrend({items,complete})` uses same normalization helper and clearly marks partial state.

- [ ] Write failing tests for displayed overview KPI scope/coverage, zero/unknown states, >2^53 exact counts, one time-bucket keyboard/click drill that clamps start/end, and activity failure/empty/unknown distinctions.
- [ ] Run only new test files; confirm intentional failures before implementation.
- [ ] Rebuild overview as readable KPI row plus purposeful project summaries. Retain source page/complete-only aggregation. Project details use grouped panels and clear section heads.
- [ ] Replace text-only trend buttons with accessible native SVG/HTML charts with exact count labels/tooltips and keyboard buttons. Show total-test and failure series/lane meanings explicitly; do not visually assert PASS when the source only proves activity. Error rankings use meaningful comparable bars and retain every original drill action.
- [ ] Rebuild activity as compact heatmap with legend and stable device/time labels. Keep96-grid bound, exact/missing device filtering and partial/empty meaning. Return to actual records/device routes with unchanged scope calculations.
- [ ] Run new tests, `ProductionToolsWorkspace.test.tsx`, and `npm run test:bundle`; retain first failures and targeted fixes. Commit task-owned files and write `.superpowers/sdd/visual-20261111/task-2-report.md` with exact evidence.

### Task 3: Records, drawer, comparison and investigation/handoff surfaces

**Files:** Modify `details.tsx`, `investigations.tsx`; create `details.css`, `detailsVisual.test.tsx`; optionally split view components while preserving original exports. Do not edit boards/workspace/primitives or investigationState/resolution/API/nav behavior.

**Interfaces:** Consume Task1 primitives and existing BoardProps/Coverage/ReadBlock exports. Preserve `result`, `RecordTable`, `Records`, `HistoryPage`, `CatalogPage`, `Parameters`, `Compare`, `EventSidebar`, `InvestigationPanel` public exports and all operation handlers.

- [ ] Write failing tests for explicit PASS/FAIL/unknown badges, selected symptom visibility, drawer header/semantic grouping, and clearly separated primary/comparison/log/handoff areas. Preserve existing click/CSRF/payload tests rather than weakening them.
- [ ] Run new tests to demonstrate missing presentation semantics.
- [ ] Rebuild records/history/catalog using consistent section headers, table tools, result pills, stable metadata, row attention treatment, captured-page navigation and partial/empty callouts. Keep all event selection/history/SN and capture IDs intact.
- [ ] Rebuild event drawer, parameter/difference views and comparison using named sections, result treatment, readable definition lists and explicit primary/comparison labels. Core actions remain visible and accessible; preserve candidate lookup scopes.
- [ ] Rebuild investigation panel into structured header/status/actions, core object sections, metadata details, notes and handoff recovery. Keep conflict/readonly/stale binding statuses and restore/fork/generate flows intact. Style via isolated details.css.
- [ ] Run new tests, full `ProductionToolsWorkspace.test.tsx`/`shell.test.tsx` and `npm run test:bundle`. Commit only owned files and write `.superpowers/sdd/visual-20261111/task-3-report.md` with evidence.

### Task 4: Integration, independent review and mainline delivery

**Files:** Root owns integration fixes and `docs/verification/production-workbench-visual-2026-11-11.md`; task progress at `.superpowers/sdd/progress.md`.

- [ ] Obtain task-scoped reviews from fresh agents with brief/report/diff package; resolve Critical/Important findings and record Minor findings.
- [ ] Run combined focused tests: `npm test -- src/workflow/productionTools src/workflow/api.test.ts src/workflow/navigation.test.tsx` and `npm run test:bundle`.
- [ ] Run final general frontend using the known PF environment: `WORKFLOW_TEST_PYTHON=/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform/.venv/bin/python npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx`. E30 remains a separate release gate.
- [ ] Inspect final CSS cascade, responsive/contrast calculations, semantic legend, all data/read/write guard regressions and production bundle constraints. Do not claim a browser render was accepted.
- [ ] Create full base..HEAD review package, obtain broad independent code review, fix/review findings and rerun affected checks only.
- [ ] Verify original mainline and remote have no unseen changes, preserve original `.gitignore`/README/knowledge modifications, fast-forward reviewed branch into main, rebuild from the actual original directory and record exact hashes. Commit verification docs and push mainline under the existing delivery authorization; document production deployment separately.
