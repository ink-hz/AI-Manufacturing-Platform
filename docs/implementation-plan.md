# Manufacturing Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. User authorized design refinement, development and production rollout without another permission checkpoint.

**Goal:** Ship a native platform manufacturing workbench with configurable business lines, durable stage records/tasks, participants/BOM handoffs/system relationships and truthful connection status.

**Architecture:** Business API and browser library live in AI-Manufacturing-Platform. A thin AI-Agent-Platform adapter loads the versioned, read-only business Python package and serves its browser assets; the frontend mounts the library inside the existing platform shell. Reuse platform authentication/CSRF/authorization and persist manufacturing SQLite separately. No new Nginx paths or service-to-service identity protocol.

**Tech Stack:** Python 3.11+, FastAPI/Pydantic 2, SQLite; React 19, TypeScript, Vite library IIFE, Vitest/jsdom. Use the existing platform Python environment for local tests. Browser/page acceptance remains with the user.

## Global Constraints

- Keep the UI to overview and stage workspace. Collapsed contextual help and collaboration/data relationships; no document grid, fake operational metrics, or unimplemented AI chat.
- Default groups: internal/external. Stable line IDs: cameras (自研相机，含数采相机), 3d-printers (3D 打印机), oem (OEM 代工代料). Stable stages S1–S9.
- Business definitions are configurable with stable IDs, display order, enabled flags and per-line stage IDs. Rename/reorder never moves or erases persisted data. Unknown/disabled line or stage fails explicitly.
- Stage records/tasks isolated by line and stage; no automatic cross-line copies. Task completion is not process confirmation or production completion.
- Only trusted platform owner/admin can read/write initially. Auth absent -> 401; member/viewer -> 403. Hard-stale directory -> read allowed/write 503. Server enforces authorization independent of UI.
- Authenticated API responses and assets are private/no-store. Validation errors never echo submitted business data. No credentials in records, source, logs or reports.
- Optimistic versions protect stage and task edits. A repeat create-task request with the same operation ID has the same result; changed payload under the same ID conflicts.
- Actual ERP/MRP/MES vendor/endpoint/access are unknown. Deliver system relationship registration; never claim connected/synced or call arbitrary saved URLs. Real connector work waits for documented system identity and access.
- Platform production uses an ordered 37-input Compose chain in the current runtime maintenance manifest. Preserve that chain, mounts/networks, and actual runtime patch. Never run generic deploy.sh or nginx -t/-T -c on production.
- Do not use browser automation. Focused API/DB/component tests and production HTTP/static-content verification; report user page acceptance separately.

## Task 1: Manufacturing business API and persistent domain package

**Files:** Create `pyproject.toml`, `src/manufacturing_platform/{__init__,catalog,models,repository,api}.py`, `src/manufacturing_platform/catalog.json`, `tests/test_catalog.py`, `tests/test_repository.py`, `tests/test_api.py` in the manufacturing feature worktree.

**Interfaces:** The platform provides trusted identity through an injected callback; the business package never trusts browser identity headers. Export exactly:

```python
def build_router(*, database_path: str, assets_dir: str, authorize, release: str = "development"):
    # authorize(request, write=False) -> dict(user_id: str, display_name: str, read_only: bool)
    # callback may raise fastapi.HTTPException; resolve awaitables if needed.
    ...
```

Router prefix `/api/v1/manufacturing`; `/access` returns `{allowed:true,can_edit:bool,available:true,release:str}` for authorized callers (403 can return allowed:false; unauth stays401). `GET /health` reads DB and returns release/readiness without records. `GET /catalog` returns `{groups,lines,stages,can_edit,release}`; groups/lines use `id,name,enabled,order`, lines add `group_id,stage_ids`, camera name is `自研相机` with description `含数采相机`. Stages use `id,name,purpose,help,prompts,reference_participants,reference_handoffs,reference_systems`; all references explicitly proposed/reference, not seeded company facts.

`GET /lines/{line_id}` -> `{line,stages:[{...stage,recorded:bool,open_tasks:int}],can_edit}`. `GET /lines/{line_id}/stages/{stage_id}` -> `{line,stage,record,tasks,can_edit}`. Empty record shape:

```json
{"practice":"","participants":[],"handoffs":[],"systems":[],"version":0,"updated_at":null,"updated_by":null}
```

PUT to the same stage URL consumes `expected_version,practice,participants,handoffs,systems`; returns the saved record (version increments). Nested items: participants `{name,role,responsibility}`, handoffs `{name,from_party,to_party,version_reference,notes}`, systems `{name,kind,objects,maintainer,method,notes}`. Methods are `unknown,manual,file,api`; API registration never produces connected status. Practice <=12000 chars, max20 items per relation array, max500 chars per field, names required/nonblank, unknown body fields rejected. Read model/validation handles lists and lengths predictably. Return 409 on stale version, 404 on unknown/disabled line or stage; DB failure -> safe503. GET record does not implicitly approve facts. Saved empty practice sets recorded false even with relationships/tasks present.

POST `/lines/{line_id}/stages/{stage_id}/tasks` consumes `{title,operation_id}` (UUID operation ID, trimmed nonblank title <=300), returns task `{id,title,completed:false,version:1,created_at,updated_at,updated_by}`. PATCH `/lines/{line_id}/stages/{stage_id}/tasks/{task_id}` consumes `{title,completed,expected_version}`; returns updated task; verifies task scope and CAS. Reuse operation_id for retries, reject same ID with changed title/scope/actor. No delete endpoint. SQLite transactions, WAL/busy timeout, unique scope keys, durable close/reopen, no process-local source of truth. DB path explicitly configured and parent created, no /tmp fallback.

Assets: GET `/assets/{asset_name}` permits only `manufacturing.js` and `manufacturing.css` from assets_dir, correct MIME, no directory traversal/SPA fallback. All routes gate auth before persistence or asset reads, mutations call authorize(write=True). Add a private APIRoute wrapper for fixed validation errors/no-store including errors.

- [ ] Write tests first for empty/read/save/reopen, line isolation, CAS conflict and independent SQLite connections, idempotent task create/reopen/scope rejection, config rename/order/invalid definitions, safe errors, permissions/read-only/assets.
- [ ] Run RED: `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests` and record feature-missing failure.
- [ ] Implement the package and hand-written catalog with short contextual prompts, source references as simple text/links and per-stage proposed responsibility examples.
- [ ] Run focused GREEN, then the package suite once; commit and report exact RED/GREEN evidence.

## Task 2: Two-view browser library

**Files:** Create `webui/package.json`, lockfile, TypeScript/Vite config; `webui/src/{index,App,api,types}.tsx` (use .ts where no JSX), `webui/src/components/StageWorkspace.tsx`, `webui/src/components/RelationshipsEditor.tsx`, `webui/src/manufacturing.css`, focused `*.test.tsx`/`api.test.ts`.

**Consumes:** Task1 API shapes above. **Produces:** Vite IIFE files `webui/dist/manufacturing.js`, `manufacturing.css`, with no HTML entry, runtime API URLs or secrets baked in.

```ts
window.OrbbecManufacturing = {
  mount(element: HTMLElement, options: {
    apiBase: string; csrfToken: string; readOnly: boolean;
    onAuthError?: () => void;
  }): { unmount(): void }
};
```

Use credentials same-origin and `X-CSRF-Token` on writes (verify platform exact header and follow it). Default business group internal and line cameras. Two group tabs, second-level enabled lines, no unnecessary chooser for one line. Vertical stages, only recorded/open tasks indicators. Stage workspace shows back link, breadcrumb, one-sentence purpose, collapsed help, current practice read/edit/save/cancel, tasks and collapsed completed list. Below, collapsed collaboration/data section supports add/edit/remove relation rows inside the same versioned stage draft; no unsaved local changes reported as persisted. Clear practice -> unrecorded. Save whole record including relationships via expected_version; 409 preserves draft and offers reload-with-explicit-choice, never silent overwrite. Tasks use operation UUID retained on retry and expected_version on patch, show failures, no auto title rewriting. Add/update real data refreshes overview on return. Preserve selected line and overview scroll while switching views; browser beforeunload and internal navigation protect dirty drafts. Parent external navigation sees beforeunload; expose any necessary dirty integration contract to Task3 explicitly.

Read-only disables all write actions. 401/403 clears sensitive loaded state and calls onAuthError (or displays access denied). Read/save failures retain appropriate loaded/draft state with retry. Show system relationship badge `关系登记，尚未验证连接`. Reference participants/system roles clearly separate from saved actual relationships. Fields accessible and responsive, no browser automation. Scoped `.mf-` CSS, no global body resets, inherit platform typography/theme, quiet panels, no giant KPI cards. Do not render knowledge articles as page menu. Use no external CDN/network resources.

- [ ] Add meaningful Vitest/jsdom tests first for default/group+line switching, empty and saved stage views, scope isolation, successful mutation and failure retention, CAS conflict and read-only, relationship editor and truthful connection badge. API tests check headers and idempotency body.
- [ ] Verify RED, implement minimal UI, verify GREEN, `npm run build`, report bundle names/global mount interface and commit.

## Task 3: Platform bridge, identity and navigation

**Files:** In platform feature worktree create `backend/app/manufacturing.py`, `backend/app/manufacturing_paths.py`, integration tests; modify `backend/app/main.py`, control-plane `authorization.py,middleware.py,auth.py,routes_auth.py`; frontend `router.ts,auth.ts,documentTitle.ts,App.tsx,panoramaNavigation.ts,panoramaTypes.ts,platform/PlatformSidebar.tsx` as required; create `pages/ManufacturingPage.tsx` and focused tests.

**Consumes:** business router and IIFE mount contract. **Produces:** `/manufacturing` native page and exact backend route authorization, safe login-return/deep-link behavior, sidebar entry gated by access probe. No standalone service/Nginx changes.

```text
PLATFORM_MANUFACTURING_ROOT=/opt/manufacturing
PLATFORM_MANUFACTURING_DATABASE_PATH=/app/data/manufacturing/workbench.sqlite3
PLATFORM_MANUFACTURING_RELEASE=<manufacturing SHA>
```

Load trusted `<root>/src/manufacturing_platform` via explicit import path and call build_router with `<root>/webui/dist`. Feature missing/bad config yields authenticated safe503/available:false, not whole-platform startup failure. Authorizer reads request.state.auth_context, requires owner/admin, returns stable actor ID/name; hard_stale write503. No identity mode must not bypass manufacture auth. Register precise method/route tuples for catalog,health,access,assets,line,stage,task APIs in central AuthorizationService and same mutation hard-stale gate. Platform global CSRF must apply unchanged; add only required `/manufacturing` shell recognition to login return/auth shell logic with path validation.

Native page fetches access then loads authenticated JS/CSS once per asset URL, mounts into a dedicated DOM element with account CSRF and prefix-aware API base, unmounts correctly under React StrictMode. Retain platform sidebar/header and deep route title. Route may use `/manufacturing` only, business inner views stateful; if using child paths define and validate them rather than arbitrary catch-all. Handle unavailable/denied/error states without fake UI. Navigation visible only authorized/available; assets never public manifest entries. Preserve all existing unrelated scope checks.

- [ ] Add tests first for 401/member403/admin success, hard-stale read/write, missing/invalid CSRF through real platform middleware, authenticated asset delivery and unknown paths, safe login return, sidebar/route/wrapper mount failures and dirty navigation.
- [ ] Verify RED; implement small adapters; verify GREEN with affected auth/router/API suites and frontend build. Do not repeat unrelated full suites for every small change.
- [ ] Commit, request spec+quality review, merge validated feature branches into their main branches preserving user untracked files, record both exact SHAs.

## Task 4: Production rollout and evidence

**Files:** Create checked-in `deploy/` release/verify scripts and `docs/release-2026-10-27.md` in manufacturing repo; platform release record in appropriate docs/operations. Reuse existing production controlled executor and maintenance-chain contract described in docs/deployment-audit.md.

- [ ] Validate final package tests, platform affected suites/build, clean diffs and review findings. Build immutable release archive from recorded manufacturing commit, include actual compiled assets with manifest hashes and source revision. No credentials/data in archive.
- [ ] Use current runtime labels/maintenance manifest as authority, preserve 37 ordered Compose inputs and append one manufacturing overlay with exact platform image/release, read-only manufacturing release mount, independent writable data directory owned10001, root/restart/health/network settings unchanged. Preserve all current runtime SDK/FAE patches. Candidate readiness before cutover; backup record and deterministic rollback to exact previous chain.
- [ ] Protected production probes use documented controlled executor/session verification, not another user's cookie. Verify unauth401, non-granted403, real authorization/CSRF and new asset MIME+full body hashes, API readiness, persistence/restart with isolated disposable records only where authorized. Do not create success records by SQL. Delete no user data.
- [ ] Verify other app entrances/representative static hashes and service status. Record running image/release, maintenance-chain file, package SHA and test counts. User browser/visual acceptance remains unexecuted and is reported separately. Existing unhealthy unrelated services are recorded as baseline, not claimed fixed.
- [ ] If vendor documents arrive, add a separate narrowly specified read-only connector step with actual field mapping/auth/rate/error behavior and its own acceptance; otherwise explicitly leave genuine ERP/MRP/MES connectivity unverified while shipping relationship registration.
