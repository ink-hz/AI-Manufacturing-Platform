# Manufacturing Visual Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task by task.

**Goal:** Deliver the approved manufacturing visual hierarchy and business-first home using current truthful scoped data.

**Architecture:** Scoped semantic design tokens and one reusable status component apply across shell, ledgers and object views. A home presentation model consumes existing Dashboard/project summaries/actor tasks without backend or schema changes, preserves read ownership, and explicitly distinguishes missing/bounded/page data.

**Tech Stack:** Existing React19/TypeScript/Vitest5/CSS; no new dependency or backend protocol.

## Global Constraints

- User approved deep blue-gray navigation, pale gray canvas, white surfaces, clear typography/spacing, one main action emphasis and semantic status colors with labels/icons.
- Scope all visual rules under .mf-root; do not affect the host Agent platform. Keep responsive navigation, keyboard focus, account controls and reduced-motion preferences.
- Only real existing scoped data may produce metrics. No invented overdue, shortage, release-rate or WIP figures. Page-derived counts explicitly say 本页; bounded task totals disclose partial/lower-bound scope.
- Delivery metric counts projects with positive current_order_quantity and positive remaining_to_ship; quality metric sums available complete current-project open_nonconformances; work orders use Dashboard.counts.work_order. Missing/invalid/mismatched project scope must not produce fake0.
- Never sum quantities across different units or equate shipped with fully accepted/quality/cost/project closure. Show original decimal strings/units for project balances.
- Preserve global navigation/drilldown context, request ownership/late response guards, permissions/read-only/identity, CAS/drafts and entire Markdown handbook. No legacy product entry/fallback.
- No backend/PF source or schema changes, mock reseeding, dependency upgrades, browser automation/employee sessions, real ERP calls, messages, Nginx changes/tests/reload, or unrelated services.
- Current demo three databases/WAL, five dataset settings and server import manifest remain. Source-only rollback must retain post-release user edits.
- Preserve first failures; run affected meaningful tests and final frontend/build, with final actual Linux candidate36 before deployment. No repeating unrelated old whole-repo suites.
- Work only in MF /Users/neo/Developer/work/AI-Manufacturing-Platform/.worktrees/visual-hierarchy; canonical user materials and shared dependency installation stay intact.

### Task 1: Unified visual hierarchy and truthful business home

**Files:** Modify webui/src/console/console.css and ConsoleShell.tsx; workflow/workflow.css, WorkflowHome.tsx, GlobalLedger.tsx, GlobalTasks.tsx, OrdersWorkspace.tsx/ObjectTable, and precise WorkflowApp integration. Create focused StatusBadge/status semantics and home presentation helper modules/tests. Touch other object/quality/project views only to use the same visual grammar, without business changes.

**Interfaces:** Existing WorkflowApi.tasks(limit,offset,projectId?,signal?), Dashboard.counts/project_ids/project_count, current ProjectDetail.summary/quality_summary and WorkflowTarget/onNavigate callbacks. Status component accepts actual state plus optional kind/blocking facts; no arbitrary title-text inference.

- [ ] Explore current CSS inheritance, status vocabularies and parent async producers. State exact metric definitions and loading rules in report before relying on them.
- [ ] RED semantic/behavior tests: status tones including unknown/cancelled/accepted-vs-completed; scoped data aggregation with missing and mismatched metadata, positive decimal quantities, mixed units, quality missing, task truncation/lower bound; real task/module clicks; owned tasks read cancellation/late401 guards; keep current dashboard failure independent from other modules. CSS low-impact values need no snapshot tests mirroring implementation.
- [ ] Implement tokens and shared status visuals. Normal status text must have measurable foreground/background contrast, and text/icon semantics remain readable without color. All statuses/important actions use shared roles rather than per-module arbitrary colors. Use existing inline SVG patterns, no bitmap generation/new library.
- [ ] Implement home with four honest focus metrics, bounded priority queue, delivery overview and compact business shortcuts. Reuse API/project metadata safely; explicit loading/error/retry/partial/empty states. Primary home action handles tasks, new-project action remains available with secondary emphasis. Cards/list rows keep actual entity/action contexts.
- [ ] Apply hierarchy to global ledgers/tasks and shared object table/details, with business-specific title/total, sparse attention emphasis and clearly page-scoped indicators. Preserve existing filter/tab/page/processing actions and labels where useful. Do not introduce dates/quantity balances not present in DTOs.
- [ ] Add focused tests and run them GREEN; verify role foreground/background contrast numerically; run current nav/account/handbook tests and one full frontend suite plus strict build/bundle. Run actual local E30 using TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform (current real canonical source) and existing fixture; preserve original6 and global navigation assertions.
- [ ] Self-review source, typography/contrast, responsive CSS scope and truthful KPI labels. No browser/Playwright/CUA. Commit exact feature files/docs; full report .superpowers/sdd/task-1-report.md with first failures, tests/timing, metric definitions, limitation and SHAs. Do not stage root-owned webui/node_modules symlink.

### Controller verification and release

- [ ] Independent task BOTH review, fixes/re-review, then whole-branch integration/read-model/rollout review. Retain raw failures and final reports.
- [ ] Refresh actual live baseline, complete current input chain, source/static maps, all3DB fingerprints, existing workflow configuration and protected other containers. Do not assume Git tip equals deployed runtime.
- [ ] Merge reviewed MF source to main. PF source remains unchanged at current released exact commit. Build immutable committed source with zero backend overlay and the current base image/manifest; reuse only pinned lock-compatible Node runtime.
- [ ] Private UID10001 readonly actual Linux candidate with bounded owned evidence mount and complete36 acceptance; inspect E30 and new actual UI source/static pins. No production data or identity fixtures in application configuration.
- [ ] Back up all current3DBs then guarded source/image-only cutover preserving complete ordered overlays and existing mounts/security/settings. Source-only rollback preserves current databases/WAL.
- [ ] Independently read new served assets/source, actual domain counts, current-role visible scopes and all prior logical rows. Check app health/anonymous access and unchanged original other services/Nginx. Actual browser visual acceptance is user-owned and recorded as unexecuted.
- [ ] Commit accurate release record, archive private evidence and cleanup only owned merged worktree/dependency symlink/candidate filesystem. Preserve canonical drafts, current demo manifest and all production source/maintenance/backup inputs.
