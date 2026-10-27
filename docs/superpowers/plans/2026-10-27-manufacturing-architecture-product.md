# Manufacturing Architecture Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the approved engineering-package → handoff → production-readiness workflow with actual system/data ownership and actionable project attention.

**Architecture:** Add focused collaboration domain modules and durable tables beside existing project JSON. A shared query projection composes control facts into existing project/dashboard results. Keep platform authorization and rendering shared; source manifests and SQLite backup govern deployment.

**Tech Stack:** Python3.11+, FastAPI, Pydantic2, SQLite WAL, React19/TypeScript/Vite, pytest and Vitest/jsdom; no new dependencies.

## Global Constraints

- Approved spec: `docs/superpowers/specs/2026-10-27-manufacturing-architecture-product-design.md` (user approval: “开始吧”). Existing handbook stays ONE complete document; do not modify its source.
- Preserve all existing projects, legacy workflow, tasks, dirty drafts and handbook return behavior. Never seed production business facts from templates.
- All endpoints use the SAME private router authorization, readOnly, CSRF/Origin, no-store, abort/disposal and exact platform route allowlist. Owner/admin only; do not invent external approval authority or identities.
- Manual records must say manual; no network connector/secret settings or “connected/synced” claims. No messages to customers/suppliers and no equipment or external posting actions.
- Creation AND state actions use actor/scope/content-bound operation UUIDs; mutable objects use expected_version; cross-object checks and writes are one SQLite transaction. Durable events retain full history, not the capped project activity array.
- Source links are references, not server fetches. IDs are stable. Evidence/source/revision and external time versus recorded time remain distinct. Superseding revisions never rewrite existing references.
- No browser automation: user owns browser/visual acceptance. Use real API/database tests and disposable synthetic candidate identity. Do not touch user-owned D docs/handbook/01-first-week.md, D02-product-and-versions.md or .mindle.json.
- Worktrees: manufacturing `/Users/neo/Developer/work/AI-Manufacturing-Platform/.worktrees/architecture-product-20261027`; platform `/Users/neo/Developer/work/AI-Agent-Platform/.worktrees/manufacturing-architecture-20261027`.
- Python: `/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python`; command `PYTHONPATH=src <python> -m pytest`. Installed node_modules are reused; no package updates.

## Shared HTTP Contract

All paths below are relative to `/api/v1/manufacturing`. Lists return `{items:[...]}` except composite responses. Every object has id,version,created_at,updated_at,updated_by. Write bodies include operation_id UUID, and expected_version for existing objects. Fields are strictly validated, bounded, unknown fields forbidden; no caller-supplied actor/derived aggregate.

- `GET /collaboration` → `{systems,authorities,handoffs,attention}`. Project-bearing rows include project_id/project_name; filter archived project attention.
- `POST /systems`, `PATCH /systems/{system_id}` → system. Fields name,kind,line_ids,business_owner,it_owner,usage (unverified/purchased_unused/used_bypassed/manual_effective/missing),method (unknown/manual/file/api),notes,active (defaulttrue). Retired system references stay readable.
- `POST /authorities`, `PATCH /authorities/{authority_id}` → authority. Fields line_id,object_type (material/ebom/mbom/work_order/inventory/inspection/equipment),system_id,entry_point,owner,notes,active. Enforce one active authority per line/object; selected system must cover line and be active; removal/deactivation preserves historical rows.
- `GET /projects/{project_id}/controls` → `{packages,handoffs,readiness,events}`. events chronological descending; paging via limit/offset if necessary, durable retention unlimited.
- `POST /projects/{project_id}/packages`, `PUT /projects/{project_id}/packages/{package_id}` → package. Fields title,product_ref,scope,provider,owner,customer_version,internal_version,approval_party,approval_status (unknown/confirmed/not_required),approval_evidence,items. Item fields id,kind (ebom/mbom/drawing/route/sop/firmware/test_program/test_spec/other),title,source_system_id (nullable),source_name,source_ref,revision,evidence,owner,status (pending/verified/na),reason. Source system optional for manual carrier, but source_name and source_ref identify it. All items unique IDs.
- `POST /projects/{project_id}/packages/{package_id}/actions` → package. action submit/verify/return/revise/invalidate; reason for return/invalidate; all operations include UUID/CAS. Package status draft/review/verified/returned/invalid. Draft/returned editable; verify requires reviewed items with source/revision/evidence or explicit NA reasons, owner, scoped product; OEM tracks separate customer/internal versions and approval party (unknown approval stays unknown). Verify freezes content. Revise creates a new draft record with same family_id, revision+1 and supersedes_id; never edits old content. Invalidate preserves prior facts and resets current dependent checks to pending with audit reason.
- `POST /projects/{project_id}/handoffs` → handoff. Fields package_id,from_party,to_party,to_system_id nullable,owner,due_date,method,evidence,occurred_at. Only fixed verified package revisions can be handed off. Each receiving party gets independent row. status draft/sent/received/returned/cancelled.
- `PATCH /projects/{project_id}/handoffs/{handoff_id}` → handoff. Fields action send/receive/return/cancel,received_revision (integer),evidence,occurred_at,reason plus UUID/CAS. Receive requires sent, matching package revision, evidence, actor and external event time. Returned requires reason; a corrected handoff is a new record. Clearly label all statuses as manual registration; never infer external posted/approved.
- `POST /projects/{project_id}/readiness` → readiness. Fields title,package_id,work_order_ref,scope,planned_use_date,required (defaulttrue),owner,items. Item fields id,kind (version/materials/equipment/people/first_article/customer/customer_material),label,required,owner,due_date,status(pending/verified/blocked/na),evidence,source_ref,source_system_id nullable,reason,valid_until nullable,package_item_id nullable,supply_mode (unknown/self/customer/mixed),first_article_result (unknown/planned/passed/failed/na). Server validates typed dates. Selection/scope/package binding snapshot fixed after creation. Create binds only verified/frozen packages; draft/review/returned/invalid packages rejected422. Optional supersedes_id + supersedes_version explicitly replace an older readiness: same project/work_order_ref/scope and required flag, same package family with a strictly newer verified revision, preserve required check IDs/kinds/applicability (new required checks may be added). Replaced row gets superseded_by metadata/version+1 and immutable audit; stale/two competing replacements409. Inactive historical checks remain readable but are excluded from current status/attention and cannot be edited or generate new issues. New replacement is independently rechecked; it never inherits old completion. Invalidation skips already superseded history. These are lifecycle details of the approved “new revision recheck, old history retained” design, not a new external action.
- `PUT /projects/{project_id}/readiness/{readiness_id}` → readiness, body items + UUID/CAS; item IDs/types/required applicability fixed. Verified requires owner/source/evidence; blocked needs reason; NA needs reason. Equipment verified requires valid_until >= planned_use_date. Version verified must reference an applicable verified package item. Required first_article verified needs passed, not merely planned. Required OEM customer condition needs external approval evidence; customer material participates in material checks. No quantity arithmetic or MRP. Overall status derived pending/blocked/complete, required NA with documented reason is excluded; invalid package cannot complete. Optional incomplete items do not create false complete required checks.
- `POST /projects/{project_id}/readiness/{readiness_id}/issues` → existing project task linked to source `{type:'readiness',id,item_id}`. Fields item_id,title,owner,due_date,priority,notes,operation_id. Create via same transaction; duplicate operation never duplicates issue. Existing ProjectTask/FlatTask exposes optional source for navigation; task completion does not change readiness status.
- Existing `GET /dashboard` adds control_attention (same attention shape as /collaboration). Existing project summary composes readiness: activated required blocked checks imply blocked; activated pending checks prevent completed; all old records without new controls retain existing semantics. Stage completion cannot overwrite readiness. Attention row: project_id,project_name,stage_id,object_type(package/handoff/readiness),object_id,item_id nullable,title,reason,owner,due_date. Package missing material→S2, handoff→S2, readiness→S4/S5.

## Task 1: Durable business domain and real API

**Files:** Create focused `src/manufacturing_platform/collaboration_models.py`, `collaboration_store.py`, `systems.py`, `engineering.py`, `readiness.py`, `collaboration_api.py`, `collaboration_queries.py`; modify `api.py`, `project_api.py`, `project_repository.py`, `project_models.py` only for registration and integrated projections/source links. Tests: `tests/test_collaboration.py` (split by domain if >500lines).

**Interfaces:** Implement Shared HTTP Contract exactly; frontend consumes its JSON. Domain code uses the current protected router and same SQLite DB, separate normalized tables/append-only event and operation logs. Stable foreign references and original project JSON coexist; no destructive migration. Unknown scopes/project/object IDs404; invalid business transitions422; CAS/UUID/authority collision409. Do not leak DB errors. Project summary/query composition must be centralized and cannot persist a competing frontend-computed status.

- [ ] Write RED real TestClient workflows for systems+authority uniqueness, package freeze/revise/invalidate, scoped handoff mismatch/independent recipients, equipment expiry, missing proof/NA reason, planned versus passed first article, OEM unknown approval, material ownership, action replay/CAS and cross-project isolation. Example:
```python
assert client.get(BASE+'/collaboration').status_code == 200
assert client.patch(handoff_url,json={'operation_id':str(uuid4()),'expected_version':1,'action':'receive','received_revision':999,'evidence':'r1','occurred_at':'2026-10-27T05:00:00Z'}).status_code == 422
```
- [ ] Run tests first and record missing-route/behavior failures, not collection/typo errors.
- [ ] Implement models, transactional stores/services and route registration; bounded typed content, reference integrity, journal events and operation replay. Core derived rule:
```python
required = [i for i in checks if i['required']]
status = 'blocked' if any(i['status']=='blocked' for i in required) else 'complete' if required and all(i['status'] in {'verified','na'} for i in required) else 'pending'
```
- [ ] Verify all linked reads, cross-object transaction rollback, archived history, separate Repository instance and process re-read, activity retention beyond200 events, project/dashboard completion projections; old124 tests still pass.
- [ ] Write `.superpowers/sdd/task-1-report.md` with commits, RED/GREEN commands/counts and exact JSON examples for frontend. Commit only scoped source/tests.

## Task 2: Product interaction and shared API client

**Files:** Create `webui/src/collaboration/{types,labels,ControlsWorkspace,SystemCollaboration,PackageEditor,HandoffEditor,ReadinessEditor,ControlAttention}.tsx/ts` as appropriate; split further by focused responsibility. Modify `api.ts`, `App.tsx`, `projects/ProjectDetail.tsx`, `projects/ProjectHome.tsx`, `projects/TaskCenter.tsx`, `projects/types.ts`, `manufacturing.css`. Tests scoped to `webui/src/collaboration/*.test.tsx` plus existing integration tests.

**Interfaces:** SAME protected request helper from api.ts; types and exact routes in Shared HTTP Contract. No raw fetch. Existing Api lifecycle/dirty guard respected. Use domain constants labels, no new dependency. Existing `onDirty(key,value)`/`requestLeave`/onChanged APIs integrate drafts, save conflict retention and refresh. New source navigation uses project_id+object_type+object_id and links task back to readiness item.

- [ ] RED tests: actual system create/edit/retire and authority create/change; project package draft edits, submit/verify/revise; handoff create/send/receive/return; readiness edit/check and create linked issue; readOnly, retained draft after409, successful write plus failed refresh does not re-create, stale response cannot overwrite newer result. Rendered root home is still projects, never a document/system directory.
- [ ] Add typed api methods using internal request and encodeURIComponent. New operation UUID stable across failed transport retry and changes require new operation; controls must not generate duplicate records. Existing input helper patterns supported; all real object lists/empty states show honest records and primary actions.
- [ ] Add five top entries: 工作台/制造项目/事项/系统协同/制造手册. Project work area offers 阶段推进/工程资料/生产准备/交接记录 without hiding current S1–S9 behavior. Display selected object in context, not a dense all-in-one form. Header key fields, compact summary, table/card collection, focused edit panel; status text and evidence links. No empty future modules or decorative graphs.
- [ ] Add server control attention on home and source-object navigation from task center. Manual status labels explicit (已登记交出/已登记接收/人工核对), unknown source/approval stays unknown. Treat package freeze/revision as real independent objects. System “API方式” never means connected.
- [ ] Preserve every old test and continuous handbook; all dirty drafts register with host and retain across handbook consultation. Define typed readable messages. Evidence URL anchors only allow platform-safe schemes; use text for plain IDs. No remote fetch or message dispatch.
- [ ] Run `npm --prefix webui test -- --reporter=dot` and `npm --prefix webui run test:bundle`; inspect component DOM tests, no browser. Report `.superpowers/sdd/task-2-report.md`, commit scoped frontend files.

## Task 3: Platform boundary and deployment candidate

**Files:** Platform `backend/app/manufacturing_paths.py`, `backend/tests/test_manufacturing_bridge.py` (actual test location inspect rg); manufacturing `deploy/candidate_verify.py` and tests as needed. No unrelated host files.

**Interfaces:** Exact route set from Shared HTTP Contract; unavailable router mirrors same set and methods. Platform standard user denied, owner/admin allowed through real authorization with CSRF/Origin and hard-stale readOnly. All new paths under same existing private mount.

- [ ] RED parameterized tests for all new allowed method/path patterns, wrong methods, malformed/missing suffix and nested path rejection; both enabled sibling source and unavailable mode. Use real trusted synthetic sessions only in isolated tests.
- [ ] Add exact method/path tuples to MANUFACTURING_ROUTES; no prefix allow-everything. Preserve existing routes. Run related bridge and authorization tests once per justified change.
- [ ] Extend real network-none candidate to create disposable system, authority and project, package workflow, mismatched receipt rejection, receipt, preparation blocked/complete, issue linked to source, invalidate/new version isolation and separate-process persistence; actual app.main.create_app/middleware. Ensure full exact published handbook data and resources still checked. Do not create business data on production.
- [ ] Report `.superpowers/sdd/task-3-report.md` (manufacturing worktree) with exact files/tests/source baselines and commit each repo.

## Task 4: Review, mainline integration, build, rollout

**Files:** Both repos' active product design/release docs and README; existing `deploy/build_artifact.py`, `install_payload.py`, `release.py` reused (modify only concrete demonstrated release defect).

**Interfaces:** Baseline at task start: image4d986906…, runtime platform59f97fee…, manufacturing161292be…, chain40. Current manifest `/opt/orbbec-agent-platform/staging/manufacturing-handbook-continuous-20261027/future-maintenance.json`, SHA256f192c3a409c0b0e4e9e2d82c97bc0be5723be269db0959f8eddb2df28a11418f. Reread actual baseline before rollout, do not assume unchanged.

- [ ] Task-scoped reviews and broad final review with exact diff package; resolve Critical/Important findings with focused RED/GREEN fixes, retain no silent incomplete features.
- [ ] Merge reviewed branches into main/master preserving user files; build exact merged commits using clean Git exports. New backend delta approval contains only manufacturing_paths.py relative to current f5cc7855 source baseline; record base and new byte hashes, no whole-directory replacement.
- [ ] New private local artifact/stage `manufacturing-architecture-product-20261027`, unique image tag includes both commits. Baseline private JSON pins actual image, chain, source and last maintenance. Use exact tools:
```sh
python deploy/build_artifact.py --manufacturing-repo /Users/neo/Developer/work/AI-Manufacturing-Platform --platform-repo /Users/neo/Developer/work/AI-Agent-Platform --manufacturing-sha "$MF_SHA" --platform-sha "$PF_SHA" --platform-base-sha f5cc785595801cefad827b7068dc43ce6c732704 --baseline /tmp/manufacturing-architecture-baseline-20261027.json --output /tmp/manufacturing-architecture-release-20261027
```
- [ ] Upload exact installer and payload, install then release prepare→candidate→cutover. Preserve root readonly,UID10001,15mounts,data directory,networks,29other containers and Nginx. Snapshot SQLite before schema init; application rollback preserves current DB/WAL.
- [ ] Verify healthy/restarts0, exact source/static/document manifest, anonymous boundaries and immutable source metadata. Record actual commits/image/backup/maintenance chain41 and public checks. Browser acceptance explicitly user-owned. Push platform master; preserve manufacturing local repo history.
- [ ] Update product design to approved v0.4 and release record, mark this plan complete with evidence. Remove only clean merged task worktrees and own node_modules symlink.
