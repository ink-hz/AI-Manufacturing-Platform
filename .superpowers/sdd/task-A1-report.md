# Task A1 completion report

Date: 2026-10-28. Scope: versioned workflow access, isolated project/grant store, and PF host protocol. No A2–D business actions were implemented. Worktrees: MF `feat/manufacturing-full-workflow`, PF `feat/manufacturing-workflow-host`.

## Commits

- MF `bc48225d6aa2d79743b15cbf391ea06a0ed3f729` — `feat: add isolated workflow identity and store`.
- PF `8f840b5e54c2914bfadaaee7990e20cc636b2d2f` — `feat: host scoped manufacturing workflow protocol`.

## Files and decisions

- MF: `src/manufacturing_platform/__init__.py`; new `src/manufacturing_platform/workflow/{__init__,api,authorization,commands,contracts,queries,schema,service,store}.py`; `tests/workflow/{__init__,conftest,test_identity_store,test_contracts,test_a1_security}.py`. The public API is version 1. A typed strict contract validates project creation, grants, UUIDs, policy booleans and canonical decimal quantities. `WorkflowHarness` supplies fixed synthetic identities, authorized API helpers, persistent reopen, isolated paths and read-only database inspection for later tasks.
- The domain DB is initialized only on an authenticated workflow request, validates schema/dataset metadata on every transaction, uses WAL/FK/busy timeout and `BEGIN IMMEDIATE` for writes. Project creation and grant changes share dataset/actor/operation idempotency, request hashes, CAS for grant versions, and atomic audit. Project access is queried on each request; an active grant with no business role confers no read access. Subject grants use the host's trusted resolver. Existing legacy files are never used as the domain or authority database.
- PF: `backend/app/{manufacturing,manufacturing_paths,main}.py`, `backend/app/control_plane/{auth,authorization,routes_auth}.py`, `backend/tests/{test_manufacturing_workflow_bridge,test_manufacturing_bridge}.py`, and affected `webui/src/{App.tsx,App.manufacturing.test.tsx,manufacturingApi.ts,pages/ManufacturingPage.tsx,pages/ManufacturingPage.test.tsx,platform/PlatformSidebar.tsx,platform/ManufacturingNavigation.test.tsx}`. Main passes the existing `WebSessionRepository` active-user lookup. Workflow routes have an exact method/template allowlist and trusted AuthContext identity. Member shell and workflow access are permitted while legacy CRUD remains owner/admin. Origin, CSRF, no-store and hard-stale middleware remain in force.
- A configured workflow that lacks a resolver or has path/storage failure returns 503 on `/workflow/access`; its legacy router remains available. An old release lacking the versioned export returns a protocol-1 legacy-only bootstrap, and still serves legacy assets. The frontend probes workflow access first, falls back to legacy only on 404, loads private assets at the selected release, and passes bootstrap to the manufacturing mount. Future commands are explicitly unsupported until their domain task; trace/exchange routes are unavailable, with no success placeholder.

## Red/green evidence and verification

- Prior implementer reported an initial missing-export red; this turn did not reproduce that original red because partial code had been preserved. This turn observed red for the missing `resolve_workflow_subject` host keyword (TypeError), missing asset release acceptance (expected 409, got 200), active empty-role grant access (expected false, got true), and the shared Quantity type accepting invalid input. Each was followed by a focused green run.
- MF: `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest tests/workflow/test_identity_store.py tests/workflow/test_contracts.py tests/workflow/test_a1_security.py -q` → **11 passed**.
- PF: `TEST_MANUFACTURING_RELEASE_ROOT=/Users/neo/Developer/work/AI-Manufacturing-Platform/.worktrees/full-workflow PYTHONPATH=backend /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest backend/tests/test_manufacturing_workflow_bridge.py backend/tests/test_manufacturing_bridge.py backend/tests/test_r1_authorization.py -q` → **841 passed**. An earlier run had 8 setup errors because MF `webui/dist` had not yet been built; after the MF build it had 2 failures from the legacy-only route inventory assertion. The assertion now checks the intentional legacy plus workflow set and the final run passed.
- PF UI: `npm --prefix webui test -- src/pages/ManufacturingPage.test.tsx src/platform/ManufacturingNavigation.test.tsx src/App.manufacturing.test.tsx` → **28 passed, 3 files**.
- MF `npm --prefix webui run build` → exit 0, `manufacturing.js` and `manufacturing.css` emitted. PF `npm --prefix webui run build` → exit 0; Vite emitted only its large-chunk advisory.
- Ruff checks and format checks of the new MF workflow/tests and focused PF Python modules passed; `git diff --check` passed in both repositories before commit.

## Review and limits

Self-review covered exact route matching, no-auth/forged-header denial, live grants and revocation, read-only and hard-stale writes, inactive subject rejection, CSRF/Origin, legacy isolation, old source loading, preview prefix, assets/release checks, path collision and transaction audit. No separate reviewer was available in this subtask; independent review remains a handoff gate before A2.

The MF legacy App still has no protocol-1 workflow workspace branch. That branch is assigned to A4; a member can receive a valid workflow bootstrap and private asset, but the existing legacy App does not yet render a member workspace. The integrated application must not be treated as deployable until the later UI and scenario task. Browser, external-system, real-model, production and 36-scenario acceptance were not executed in A1. The `webui/node_modules` worktree symlink was deliberately left untracked and out of the commit.
