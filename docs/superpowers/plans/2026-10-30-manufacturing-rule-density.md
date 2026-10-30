# Manufacturing Rule Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make manufacturing operations readable at a glance while retaining access to evidence and safety-critical states.

**Architecture:** Change presentation only in the manufacturing React bundle. A shared source-mode presenter keeps provenance honest in compact rows and disclosure summaries; native disclosure and an on-demand rule-analysis panel hold verbose evidence. The API, database and permission paths stay untouched.

**Tech Stack:** React 19, TypeScript 5.6, Vitest 5, existing manufacturing CSS.

## Global Constraints

- Preserve blockers, errors, truncation, read-only state, simulation/manual/API provenance and unknown outcomes.
- Do not alter API requests used for business writes, authorization, persisted facts or audit history.
- Do not use browser/UI automation for verification; user performs visual acceptance.
- Work from the isolated worktree based on manufacturing `5038bf7`; do not copy unrelated dirty files from the main checkout.

---

### Task 1: Compact provenance in rows and the shell

**Files:**
- Create: `webui/src/workflow/sourcePresentation.ts`
- Modify: `webui/src/workflow/OrdersWorkspace.tsx`, `webui/src/workflow/GlobalLedger.tsx`, `webui/src/workflow/WorkflowApp.tsx`
- Test: `webui/src/workflow/ruleDensity.test.tsx`

**Interfaces:**
- Produce `sourceModeLabel(mode: SourceRef['mode']): string` and `compactSource(source: SourceRef): string` for all rows and disclosure summaries.

- [ ] **Step 1: Write failing test.** Render `ObjectTable` with a `mock` source and a blocking reason. Assert the row shows `模拟系统` and the blocker, but not the external business ID or version. Include an `api` source case. Assert shell dataset mode remains visible in its existing test.
- [ ] **Step 2: Verify red.** Run `npm test -- src/workflow/ruleDensity.test.tsx`; expect the external ID/old mode rendering assertion to fail.
- [ ] **Step 3: Implement minimum.** Add a pure presenter:

```ts
export const sourceModeLabel = (mode: SourceRef['mode']) => ({manual:'人工登记',file:'文件导入',mock:'模拟系统',api:'接口采集'}[mode]);
export const compactSource = (source: SourceRef) => `${source.system} · ${sourceModeLabel(source.mode)}`;
```

Use it in the two table source cells. Remove only the shell suffix `· 人工登记保留来源凭据`; keep dataset label/mode.
- [ ] **Step 4: Verify green.** Run the focused Vitest command and `git diff --check`.
- [ ] **Step 5: Commit.** Stage only Task 1 files and commit `feat(ui): compact manufacturing provenance summaries`.

### Task 2: Put explanatory evidence behind disclosures

**Files:**
- Create: `webui/src/workflow/OperationHelp.tsx`
- Modify: `webui/src/workflow/WorkflowDetail.tsx`, `webui/src/workflow/OEMWorkspace.tsx`, `webui/src/workflow/SupplyWorkspace.tsx`, `webui/src/workflow/ExecutionWorkspace.tsx`, `webui/src/workflow/QualityWorkspace.tsx`, `webui/src/workflow/ExchangeWorkspace.tsx`, `webui/src/workflow/workflow.css`
- Test: `webui/src/workflow/ruleDensity.test.tsx`

**Interfaces:**
- `OperationHelp({children}: {children: ReactNode})` renders a closed native `details` with summary `操作说明`.
- `Source` renders a closed native `details` with summary `来源依据 · ${sourceModeLabel(value.mode)}` and existing eight fields inside.

- [ ] **Step 1: Write failing tests.** Render `Source` and `OperationHelp`; assert their `details.open` starts false, the source summary discloses `模拟系统`, and opening shows unchanged fields. Render a `ReadinessView` via an existing work-order fixture and assert checks remain visible while input versions are collapsed. Assert a current blocker stays visible.
- [ ] **Step 2: Verify red.** Run `npm test -- src/workflow/ruleDensity.test.tsx`; expect missing `details` to fail.
- [ ] **Step 3: Implement minimum.** Wrap Source facts and readiness input versions in `details`. Move the top record version into a `记录信息` disclosure. Replace only static guidance paragraphs in named workspaces with `OperationHelp`; keep dynamic alerts and status lines outside. Add small summary spacing/focus styling to `workflow.css`.
- [ ] **Step 4: Verify green.** Run focused tests plus `npm test -- src/workflow/supply.test.tsx src/workflow/workspace.test.tsx` and `git diff --check`.
- [ ] **Step 5: Commit.** Stage only Task 2 files and commit `feat(ui): disclose manufacturing rules on demand`.

### Task 3: Fetch rule analysis only when opened

**Files:**
- Modify: `webui/src/workflow/AssistancePanel.tsx`, `webui/src/workflow/oemCapabilities.test.tsx`, `webui/src/workflow/oemInteractions.test.tsx`
- Test: `webui/src/workflow/ruleDensity.test.tsx`

**Interfaces:**
- A button labelled `查看核对建议` starts with `aria-expanded=false`; clicking reveals the existing controls and results. While closed, the API is not called. The current `projectId`, `kind`, and `version` identify visible result ownership.

- [ ] **Step 1: Write failing tests.** With a fake API, assert no initial call; click `查看核对建议` and assert one call. Change project while a promise is outstanding, then resolve the old promise and assert old evidence is absent. Assert error and truncation remain visible when open.
- [ ] **Step 2: Verify red.** Run `npm test -- src/workflow/ruleDensity.test.tsx`; expect automatic initial request to fail.
- [ ] **Step 3: Implement minimum.** Add an expanded state, conditional fetch effect and abort cleanup. Key stored results/errors by project, kind and version before rendering. Keep advice summary and blockers visible within the open panel; keep detailed evidence in each suggestion's existing `details`. Update older tests to open the panel before asserting results.
- [ ] **Step 4: Verify green.** Run targeted tests and `git diff --check`.
- [ ] **Step 5: Commit.** Stage only Task 3 files and commit `feat(ui): load manufacturing advice on demand`.

### Task 4: Integration and release handoff

**Files:**
- Modify only if needed: `docs/superpowers/specs/2026-10-30-manufacturing-rule-density-design.md`
- Read: `docs/runbooks/workflow-release.md`, `docs/release-oem-capabilities-2026-10-30.md`

- [ ] **Step 1: Verify.** Run `npm test`, `npm run build`, `npm run test:bundle`, and `git diff --check` in `webui`. Record exact counts and exit codes.
- [ ] **Step 2: Review.** Compare each spec item with the code diff; confirm no business API/backend/schema changes and no hidden safety state. Inspect final worktree status and commits.
- [ ] **Step 3: Integrate.** Follow the repository's mainline process without overwriting unrelated dirty files. If deployment is authorized and all release gates are available, build from final merged refs and use the runbook's prepare/candidate/cutover chain. Otherwise provide a tested, reviewable handoff with the precise remaining release step.
