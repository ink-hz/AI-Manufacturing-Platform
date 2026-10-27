# Manufacturing Product Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace the workflow-directory home with a working manufacturing project/issue management product, and integrate the maintained handbook through the platform's existing Markdown renderer.

**Architecture:** Sibling manufacturing repository owns the business API, persisted project aggregates and IIFE React application. Platform owns trusted session/authorization/navigation plus an injected renderer using existing ArticleMarkdown; no duplicated Markdown/Mermaid stack. Project stages and tasks are separate versioned entities within durable SQLite project aggregates; legacy tables and read/write APIs are preserved.

**Tech Stack:** Python/FastAPI/Pydantic/SQLite, React19/TypeScript/Vite IIFE, existing platform ArticleMarkdown/MermaidDiagram.

## Global Constraints

- Binding product spec: docs/manufacturing-workbench-product-design.md v0.3. Default home MUST be project/action oriented, NOT a directory, chapter tree or nine-stage list.
- Business lines remain cameras (including data acquisition cameras), 3d-printers, oem; internal/external are filters and project attributes. Stable configured IDs; existing projects retain readable stage snapshots if configuration is later renamed/disabled.
- Same owner/admin trusted AuthContext permission and global CSRF/Origin; stale-directory reads allowed/writes503; no identity-mode bypass; all new routes in exact central permission tuples; private,no-store errors/assets/docs; validate before I/O and never echo submitted data.
- No seeded company/project/production facts, fake metrics, fake approvals or invented system connections. Relationship registration remains explicitly unverified. No employee session extraction/impersonation or external messages.
- No browser automation: user owns browser/page acceptance per platform AGENTS.md. Verify APIs, real middleware, durable restart, components/build and actual handbook Mermaid syntax.
- Preserve legacy stage_records/tasks/task_operations and their API behavior. Add project tables only, no destructive migration. SQLite backup before production schema changes. Rollback retains business data.
- Reuse platform components/ai-notes/ArticleMarkdown.tsx and MermaidDiagram. No new ReactMarkdown/Mermaid implementation or dependencies in sibling bundle.
- Source handbook is docs/manufacturing-system-handbook.md; fixed related document docs/workflows/manufacturing-process-overview.md. Published immutable artifact includes these exact files and handbook-metadata.json with per-file sha256/updated_at (Git ISO date). No live working-tree mount or browser editing in this scope.
- Production currently has 38 ordered Compose inputs and existing code/data mounts. Re-discover actual image/chain; append one narrow overlay changing only image/platform release/manufacturing release and replacing manufacturing code mount SOURCE. Keep existing data mount EXACTLY, all other env/mount/network/security fields and other containers. No Nginx mutation/reload or generic deploy.sh.

## Task 1: Durable project domain, APIs and handbook delivery

**Files:** Create src/manufacturing_platform/project_models.py, project_repository.py, project_api.py, handbook.py, tests/test_projects.py, tests/test_handbook.py. Modify api.py to register new routes before its private fallback. Do not change existing API signatures or frontend files.

**Consumes:** catalog.load_catalog(), legacy RecordContent/RecordWrite validation, Conflict/NotFound and the existing trusted PrivateRoute wrapper.

**Produces exact API interfaces:**

All paths below are relative to /api/v1/manufacturing. JSON reads use plain dicts; dates serialize YYYY-MM-DD or null. ISO UTC updated_at values. Actor from request.state.manufacturing_identity only.

```text
GET /dashboard -> {counts:{active_projects,blocked_projects,due_soon,open_tasks,pending_confirmations},projects:ProjectSummary[],attention:TaskWithProject[],blockers:Blocker[],activity:ActivityWithProject[]}
GET /projects -> {items:ProjectSummary[]} (includes archived; UI filters)
POST /projects ProjectCreate -> ProjectDetail
GET /projects/{project_id} -> ProjectDetail
PATCH /projects/{project_id} ProjectUpdate -> ProjectDetail
PUT /projects/{project_id}/stages/{stage_id} ProjectStageWrite -> ProjectStage
POST /projects/{project_id}/tasks ProjectTaskCreate -> ProjectTask
PATCH /projects/{project_id}/tasks/{task_id} ProjectTaskWrite -> ProjectTask
GET /project-tasks -> {items:TaskWithProject[]} (only unarchived projects)
GET /handbook?document=handbook|workflow&release=<optional SHA> -> {title,markdown,updated_at,sha256,source_path,release}
```

Schemas (all writes forbid unknown fields; strict strings/integers/bools):

```text
ProjectCreate: operation_id:UUID, name:nonblank<=200, line_id:enabled catalog ID,
 owner:nonblank<=200, product:string<=200='', customer:string<=200='',
 due_date:date|null=null, target_quantity:int1..1e9|null=null, summary:string<=6000=''
ProjectUpdate: expected_version:int>=1, optional PATCH fields name, owner, product, customer,
 due_date, target_quantity, summary (same limits), archived:bool
ProjectSummary: id:UUID, code:string, name,line_id,line_name,group_id,owner,product,customer,
 due_date,target_quantity,summary,archived,version,created_at,updated_at,updated_by,
 status:planned|active|blocked|completed|archived, current_stage_id,current_stage_name,
 completed_stages:int,total_stages:int,open_tasks:int
ProjectDetail: {project:ProjectSummary,stages:ProjectStage[],tasks:ProjectTask[],activity:Activity[]}
ProjectStage: id,name,purpose,help,prompts,reference_participants,reference_handoffs,reference_systems,
 status:todo|doing|blocked|done,owner:string<=200,due_date:date|null,blocker:string<=2000,
 practice:string<=12000,participants,handoffs,systems (legacy bounded RecordContent shapes),
 version:int>=1,updated_at,updated_by
ProjectStageWrite: expected_version:int>=1 plus REQUIRED status,owner,due_date,blocker,practice,participants,handoffs,systems (full PUT, no omission defaults)
ProjectTaskCreate: operation_id:UUID,stage_id, title:nonblank<=300,
 kind:task|issue|confirmation='task',owner:string<=200='',due_date:date|null=null,
 priority:normal|high|urgent='normal',notes:string<=6000=''
ProjectTask: id,project_id,stage_id,title,kind,owner,due_date,priority,notes,
 status:todo|doing|blocked|done,version:int>=1,created_at,updated_at,updated_by
ProjectTaskWrite: expected_version:int>=1 plus optional PATCH fields stage_id,title,kind,owner,due_date,priority,notes,status (omitted preserves; null only nullable dates)
TaskWithProject: ProjectTask plus project_name,project_code,line_id,line_name,group_id,stage_name
Blocker: project_id,project_name,stage_id,stage_name,task_id:string|null,title,reason,owner,due_date
Activity: id,created_at,actor,action,summary (server-defined safe factual label),stage_id:null|string,task_id:null|string
ActivityWithProject: Activity plus project_id,project_name
```

Persistence can use one JSON aggregate per project in NEW `manufacturing_projects` and one NEW globally unique UUID idempotency table. Serialize transactionally using BEGIN IMMEDIATE, busy_timeout, WAL and one connection per operation. Preserve entire current aggregate on a child update; check per-entity versions before change. Creation operation ID compares actor, operation kind, scope and normalized full payload; same request returns immutable original response and adds no duplicate activity, changed payload conflicts409. Stage blocked requires nonblank blocker. Project status precedence: archived first; blocked iff any stage/task is blocked; completed iff all stages AND all tasks are done; active iff any stage/task doing/done (including all stages done with pending confirmation); otherwise planned. Current stage is first doing/blocked, otherwise first unfinished, otherwise final stage. Project core version changes only on core PATCH; child versions change on corresponding child mutations. Any real child mutation refreshes parent updated_at/updated_by for recent-work ordering without changing parent core version. Every real change appends activity, return newest50, retain latest200. Reopening completed stages/tasks is allowed. Unarchived dashboard counts use actual records; active_projects counts planned+active+blocked and is labeled 在管项目 (blocked_projects is a subset); due_soon means incomplete due_date within next7days including today, not overdue. Attention sorts blocked, priority urgent/high/normal then dates with overdue first; cap20, project summary cap8; GET projects remains full actual summaries. Dashboard/flat tasks exclude archived. No DROP/DELETE legacy schema.

Handbook reader derives fixed root from resolved assets_dir ../..; enum document selects only the two fixed files. Reject supplied mismatched release409 BEFORE content filesystem I/O, after auth. Read metadata at root/handbook-metadata.json. Require matching metadata sha256 and readable regular files confined to root; missing/corrupt -> safe503. No arbitrary path selection. Router construction does no I/O. `handbook-metadata.json` shape:
```json
{"files":{"docs/manufacturing-system-handbook.md":{"updated_at":"2026-10-27T00:00:00+00:00","sha256":"64lowerhex"},"docs/workflows/manufacturing-process-overview.md":{"updated_at":"2026-10-27T00:00:00+00:00","sha256":"64lowerhex"}}}
```

- [x] Add RED HTTP/repository tests: create/retry/change-ID-conflict, two projects isolation, edit/stage progress/block/reopen, tasks+kind/priority/owner/date, status/counts excluding archive, per-child and core CAS, restart with same DB; legacy rows unchanged; bad scope/fields/limits/private errors; docs exact bytes/digest/release/auth/confined paths/missing metadata.
- [x] Run `PYTHONPATH=src <platform backend/.venv/bin/python> -m pytest -q tests/test_projects.py tests/test_handbook.py`, record expected RED failures.
- [x] Implement models/repository/registrations; reuse parent PrivateRoute and catalog references. Register exact model defaults and response interfaces above. Code step example must remain real HTTP: `response=client.post('/api/v1/manufacturing/projects',json={...})`; not SQL inserts as success.
- [x] GREEN targeted then all tests once; commit only task files. Report red/green commands, counts, exact SHA and any interface clarification to .superpowers/sdd/task-1-report.md.

## Task 2: Project-first business application and maintained handbook reader

**Files:** Rename current webui/src/App.tsx implementation to LegacyWorkflow.tsx (export LegacyWorkflow), preserve its tests with corresponding import alias; create new App.tsx, projects/{types,ProjectHome,ProjectList,ProjectDetail,ProjectForm,TaskCenter,TaskEditor,StagePanel,ActivityFeed}.tsx as needed, HandbookReader.tsx, handbook.ts, new focused tests; extend api.ts, types.ts, manufacturing.css. Do not edit platform repo or backend.

**Consumes:** Task1 exact API payloads, existing createApi.request lifecycle protections, existing relationship editor UI and stage catalog.

**Produces:** same IIFE mount contract plus optional injected renderMarkdown:
```ts
type MarkdownOptions={markdown:string;headingIds?:Readonly<Record<number,string>>};
interface MountOptions {apiBase:string;csrfToken:string;readOnly:boolean;
 onAuthError?:()=>void;onDirtyChange?:(dirty:boolean)=>void;
 renderMarkdown?:(element:HTMLElement,options:MarkdownOptions)=>{unmount():void};}
```

New root navigation `工作台 | 制造项目 | 事项 | 制造手册` with current selection indicator and clear primary action. Default is project dashboard, never LegacyWorkflow. Tight neutral/brand styling, status text plus color, balanced content panels/rows, no oversized generic KPI cards. Responsive layout; scoped mf- CSS; keep platform header/sidebar. Dashboard actual aggregates/next work, useful honest empty state. Visual contract: header with compact title + primary new-project action; a restrained numeric summary strip; desktop 2:1 project workspace versus actionable attention panel; project cards show real name/owner/due/current phase and a compact nine-segment stage-completion track. No standalone stage directory on home. New-project form is a real creation interaction; list/board switches show the same real business objects. Detail uses a compact wrapping phase rail, selected-stage work area and activity/context side panel, not a full-page form wall. Never use emoji or giant ornamental status cards. Project filter/view preferences and selected project/stage survive switching to handbooks and back. List/kanban both use actual business project cards/rows, no stages as home rows.

Extend existing api.ts returned methods using its SAME protected request function (abort/disposal/auth callbacks/CSRF): dashboard, projects, createProject, project, updateProject, saveProjectStage, projectTasks, createProjectTask, updateProjectTask, handbook(document='handbook',release?). Exact paths/shapes from Task1. Original methods and LegacyWorkflow remain. UUID operation persists on create retry; clear only successful response or explicit cancel; no duplicate project/task on network retry. Mutations rely on server results then refresh aggregates; CAS409 retains draft and safe retry/reload choices.

Stages show compact horizontal rail + selected phase action workspace. Reuse RelationshipsEditor for participants/handoffs/systems with one stage CAS save; status/owner/date/blocker/practice in same draft. Task editor supports kind/task/issue/confirmation, owner/date/priority/notes/status; can reopen completed tasks. Read-only disables every write including create/archive/status buttons. Every dirty draft registers aggregated onDirtyChange and internal nav guard; external parent's existing isDirty guard stays authoritative; beforeunload remains. Handbooks can be viewed without discarding a draft: retain mounted detail/legacy state when hidden, preserve scroll and selected stage. Never render edit/reorder actions as decorative no-ops.

Handbook helper splits H1/H2 chapters outside fenced code and preserves ALL source text (including preamble and inter-part overview). Stage chapter matching only actual H2 S1..S9 headings. Chapter directory lives inside reader only; default chapter sensible, project `了解这个阶段` selects relevant S# chapter. Render current chapter by injected renderMarkdown; no manual HTML/ReactMarkdown fallback. Retire stale document responses and renderer handles when chapter/account/view changes; no late auth callbacks. Known relative workflow Markdown link opens fixed workflow document via handbook API, hash links navigate current rendered article; unsafe/external links remain under existing renderer policy. Display actual metadata updated_at/source path in subtle header; never show raw Markdown as rendered content on missing renderer. LegacyWorkflow reachable as low-emphasis `流程现状参考` from handbook/context, not new primary navigation. If no recorded legacy data, old empty view still accessible.

- [x] Add tests RED for home not directory, create project + go detail, filters/list/board, stage block/done/reopen and failed save draft retention, task types/priority/date, reference relationships, server-only counts/activity, archive/readOnly, dirty navigation/handbook return state, parser full text/fences/S# matching, renderer lifecycle and fixed relative document links.
- [x] Implement only actual wired actions; move existing tests for preserved legacy behavior rather than deleting coverage. Existing index/API tests should remain relevant and pass; add tests for new API bodies/UUID retries.
- [x] GREEN target then whole frontend suite, `npm run test:bundle`, TypeScript build. Inspect real DOM structure in tests; no browser automation. Commit/report .superpowers/sdd/task-2-report.md with exact screens and action contracts.

## Task 3: Native platform renderer injection and exact route authorization

**Files:** Modify backend/app/manufacturing_paths.py, tests/test_manufacturing_bridge.py, webui/src/pages/ManufacturingPage.tsx and its tests; add webui/src/manufacturingMarkdown.tsx and tests if useful. Existing ArticleMarkdown stays shared; don't duplicate its logic.

**Consumes:** Task1 routes; Task2 renderMarkdown contract and IIFE export. New exact routes listed in Task1, with unchanged owner/admin policy.

**Produces:** renderer callback passed to mount that uses existing `ArticleMarkdown` inside platform createRoot. Renderer cleanup must be safe on chapter switch, host unmount and StrictMode (no nested synchronous unmount warning or stale rendering). Host may use queueMicrotask for retiring root cleanup but must invalidate immediately and never leave callbacks from retired content. Preserve current asset-release cache fix, CSS ownership, dirty guard and account/permission change behavior. No new shell paths/query permissions are required.

- [x] RED backend exact-route enumeration + synthetic trusted owner/admin/member + real AuthorizationService/CSRF, actual main.create_app registration and real sibling API+handbook fixture integration. Include stale-directory writes and unknown/private errors. Tests fixture metadata must use source snapshot docs without altering canonical user files.
- [x] RED frontend real ArticleMarkdown renders GFM table and safe HTML, injected renderer passed by wrapper, unmount behavior and no new Markdown packages. Parse actual handbook's ALL Mermaid fences using existing Mermaid configuration/parser in an isolated local test (no browser). Add tests rather than replacing renderer with an always-passing mock for reuse evidence.
- [x] Implement exact new tuples; shared renderer bridge. Run affected platform bridge/auth and wrapper/markdown suites, TypeScript/build, public manifest excludes business assets; commit/report .superpowers/sdd/task-3-report.md. Root handles merge.

## Task 4: Review, non-destructive v2 rollout and production evidence

**Files:** Update deploy/release_guard.py, release.py, candidate_verify.py and deploy/tests; add source-controlled artifact build helper if required; docs/release-product-v2-2026-10-27.md; platform operations release record.

**Consumes:** reviewed final branches; current live 38-chain bce8f412 runtime and manufacturing source3cc02ffe (re-discover actual facts, not assumed immutable baseline).

- [x] Add RED/GREEN guard tests for replacing exact EXISTING code mount source, retaining existing data mount and preserving every non-manufacturing env/mount field. Current first-release guard intentionally rejects preexisting manufacture env/mount; extend with explicit upgrade mode, preserving first-release behavior. compare_runtime validates replaced source rather than popping unchanged data as new. Pin both images/defaults and rollback chain before mutation as before.
- [x] Candidate uses actual create_app + real auth/middleware with synthetic identity in network-none UID10001 container, disposable DB. Verify project create/idempotence/CAS/phase blocking/task completion/confirmation, legacy DB preservation, new handbook exact digest/version, all asset bytes; second interpreter reads project/tasks back. Keep positive production user auth unclaimed.
- [x] Broad whole-branch code/spec/product review of both repos, one consolidated fix wave if needed. Tests appropriate to changes and actual builds. Merge main/master preserving canonical user edits/deletions/untracked material, source exact commits, source-control publication docs. Handbook current file content is user-authorized source; unrelated deleted handbook files and .mindle metadata are not part of this task.
- [x] Build from exact merged Git sources. Immutable business release contains src, JS/CSS, handbook/workflow Markdown, handbook metadata and full content manifest. New API image derives exact current live image; COPY approved backend delta and clean built platform static files, preserve all other runtime patches/image defaults. Re-discover effective Compose38-chain and append one overlay.
- [x] Before cutover, SQLite online backup under protected permissions; don't copy only live .sqlite3 ignoring WAL. Prepare/candidate preserve live service and other apps; only API cutover after gates, preserve existing data mount; rollback retains all data and old38chain. Verify actual source/static trees, docs/metadata, healthy, anonymous new API401, no-store/MIME, representative Office/FAE resources, all other containers/security/network, original Nginx hash/no reload.
- [x] Record exact versions, tests, candidate/production evidence, backup/maintenance chain and honest scope. User browser acceptance remains not_run; real ERP/MRP/MES connectors remain unverified. Update product status and README references, merge/push platform main and clean only owned worktrees after report archival.


## Execution result

All four tasks completed and independently reviewed. Deployed manufacturing0918bb19/platform73cde126, imagefcc02c82,39-input maintenancechain; schema backed up beforeupgrade, candidate+production checks pass. Runtimecode source stays these commits; laterhandbook-only build support anddocumentation are separate. See [release record](release-product-v2-2026-10-27.md). Browser acceptance user-owned; actualERP/MRP/MES unverified.
