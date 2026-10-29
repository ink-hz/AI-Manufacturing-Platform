# Business Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task by task.

**Goal:** Sidebar modules open actual cross-project business ledgers; retire the temporary old product from the workbench.

**Architecture:** Add actor-scoped global object/task read APIs using the existing registries and typed summaries. Separate global module navigation from project detail/form context, with explicit return context. Retire old App UI switching; preserve current business data and shared handbook rendering.

**Tech Stack:** Python/FastAPI/Pydantic/SQLite; React19/TypeScript/Vitest5; existing guarded release tooling.

## Global Constraints

- Only 制造项目 shows the project list. No other sidebar module may fall back to that list, including from a fresh mount with no selected project.
- Business ledgers show real typed business objects from all and only the actor's visible projects; project is optional filter/context, not an entrance gate.
- Never infer project membership, quality qualifications or business success from platform admin role. Anonymous auth, read-only, revocation, CSRF, CAS and original operation IDs remain intact.
- Use server pagination and real totals; never download all rows into frontend or show truncated prefixes as full totals. Existing per-project bounded task scope must be explicitly disclosed.
- Object drilldown and return retain module, kind/tab, project filter and pagination. New navigation/request results must not resurrect stale objects or previous identity state.
- Preserve existing project-internal forms, draft/conflict/handbook preservation, current six demo projects and every existing database record.
- Remove old product switch, menu and fallback; no historical-product entry. Reuse shared Markdown/handbook/Dialog components. No permanent deletion of old database in this task.
- No browser automation, real employee session extraction, external messages or real ERP calls. No Nginx change/reload/test. Preserve all other services and existing five dataset settings.
- Preserve first failures; run meaningful affected tests, not unrelated all-repo repetitions. Report actual pass/fail/skips and unexecuted boundaries.
- Work in MF `/Users/neo/Developer/work/AI-Manufacturing-Platform/.worktrees/business-ledgers` and PF `/Users/neo/Developer/work/AI-Agent-Platform/.worktrees/manufacturing-ledgers`. Do not modify canonical user drafts.

### Task 1: Actor-scoped global ledgers and task API

**Files:** MF workflow/contracts.py, service.py or focused new ledger.py, api.py; webui/src/workflow/types.ts and api.ts; focused tests/workflow/test_global_ledgers.py and workflow/api.test.ts. PF backend/app/manufacturing_paths.py plus affected bridge/auth route tests.

**Interfaces:**
- `GET /api/v1/manufacturing/workflow/objects/{kind}?limit=50&offset=0&project_id=UUID` returns existing ObjectPage (`items` ObjectSummary, total, limit, offset). No project filter means all visible scopes. Stable grouping/order and pagination within one read transaction; count visible project scopes then read only the selected page with registry readers and _actions. Do not add SQL status mutations or schema changes.
- `GET /api/v1/manufacturing/workflow/tasks?limit=50&offset=0&project_id=UUID` returns ActorTaskPage (`items` existing OwnedTask, total available within existing per-project task bounds, limit, offset, truncated boolean). Truncated explicitly reflects incomplete underlying scope; UI must label available count appropriately. Existing actor.read_only rule produces no actionable tasks.
- `WorkflowApi.ledger(kind, limit=50, offset=0, projectId?)` and `.tasks(limit=50,offset=0,projectId?)`. Return typed data and use existing abort/auth/no-store contracts.

- [ ] Read exact current registry/service authorization/HTTP router and host whitelist. Record selected implementation signatures for Task2 in report.
- [ ] RED tests: two visible and one private project; no implicit admin visibility; project filter unauthorized404; correct totals and cross-project boundary pagination; empty scopes; read-only action stripping; invalid pagination/kind; bounded reads; actor-specific tasks and truncated flag; host exact-route parity/auth-before-validation.
- [ ] GREEN minimal implementation reusing current scoped readers, real role/qualification decisions and task rules. Share pagination/scope helpers rather than cloning business handlers.
- [ ] Add typed frontend API methods and request URL/auth/dispose tests. Do not modify UI navigation yet.
- [ ] Run focused new tests, current identity/query/host bridge tests covering changed contracts, relevant frontend API tests. Preserve outputs and commits separately in each repository. Do not run unrelated old tests requiring removed full-workflow worktrees.
- [ ] Report exact contracts, counts, first-error paths, performance/limits and commit SHAs. Root owns production.

### Task 2: Actual business workspaces and old-product retirement

**Files:** MF webui/src/App.tsx, workflow/WorkflowApp.tsx, new focused GlobalLedger/GlobalTasks/navigation-context components, workflow.css and relevant tests/helpers. Remove or adapt old-root tests that explicitly exercise retired product; keep valid shared-reader/forms coverage. Other files only if direct consumers require it.

**Interfaces:** Consume Task1 WorkflowApi.ledger/.tasks, ObjectPage/ActorTaskPage, current project metadata, existing WorkflowDetail and per-project workspace forms. New global pages use explicit typed module configuration for tabs/column nouns.

- [ ] RED user reproduction: freshly mount without selecting project, click 订单与交付, expect actual order source numbers and business rows; project list absent. Parameterized counterparts cover supply/execution/quality/system/tasks and cross-project records.
- [ ] Implement global ledger views with named business columns, summary counts from real totals, kind tabs, project filter, server pagination, loading/error/empty states and proper refresh. Include customer/product/project context without presenting project rows as business rows.
- [ ] Centralize navigation context. Sidebar module selection always opens global module; clicking a row opens that exact project's typed detail in the current module; return restores tab/filter/page; detail actions/form mutations refresh same context and quantity results. Project internals remain accessible only through explicit project selection.
- [ ] Add direct task list and quality trace entry; scope selector is a dropdown and opens actual trace UI. No accidental project selector tables in non-project modules.
- [ ] Replace root legacy branching with one WorkflowApp entry and explicit unavailable/error states. Remove old modeAction and product switching/fallback, without deleting shared handbook/UI utilities or databases. Preserve protocol and account boundary behavior.
- [ ] Update test helpers to reflect global initial navigation rather than auto-select project for every module. Tests cover stale responses, identity changes, dirty navigation, handbook return, accurate object detail, scoped owner/read-only controls and no legacy fallback. Existing project-based command tests may explicitly enter project context where intended.
- [ ] Run affected new/module/navigation/API/handbook/account/component suites once, then the MF frontend suite and build/bundle smoke. Retain failures and fix causes without weakening business/role gates. Commit and report exact evidence.

### Controller review, integration and deployment

- [ ] Each task gets independent BOTH review; fix/re-review blockers. Final whole-branch review on both repo ranges and exact deployment impact.
- [ ] Verify current production image/container/source/full Compose chain/manifest/config and data fingerprints; preserve six new demo projects and legacy rows. Review previous durable release controller rather than replay stale paths.
- [ ] Merge clean reviewed source to MF main/PF master, keeping canonical user materials; build exact merged refs via existing artifact tooling and approved backend overlay.
- [ ] Actual Linux candidate HTTP and React/HTTP navigation regression with synthetic authorized identities and disposable persisted data; no production identity/test clocks. Preserve real failure evidence and full source/static hashes.
- [ ] Guarded cutover using full current maintenance inputs, backups of all current3DBs, existing workflow settings, exact approved source/mount delta and other-service/Nginx invariants. Source rollback preserves databases and WAL.
- [ ] Verify actual deployed bytes, health, access controls, unchanged original rows and new nav semantics. Archive evidence, record actual release and limitations, preserve server demo manifest, clean only owned merged worktrees.
