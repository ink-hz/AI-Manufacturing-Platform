# Standalone Production Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Query real native production data as an admin without manufacturing project mappings.

**Architecture:** Source-native projects replace manufacturing UUID bindings throughout config, services, private HTTP routes and snapshots. Reuse the bounded native transports, source query semantics and SDK profile. UI reads the real source directory; manufacturing business flows remain separate.

**Tech Stack:** Python3.11/FastAPI/Pydantic/SQLite, MySQL/QuestDB/OSS SDKs, React/TypeScript/Vitest and existing PF host identity middleware.

## Global Constraints

- User approved independent production queries, no manufacturing project mapping, admin-only first release. Spec: `docs/superpowers/specs/2026-11-10-standalone-production-tools-design.md`.
- Use existing isolated MF worktree `/Users/neo/.codex/worktrees/814b/AI-Manufacturing-Platform` and PF worktree `/Users/neo/Developer/work/AI-Agent-Platform/.worktrees/native-production-tools-20261110`; both branches `codex/standalone-production-tools`, starting MF a932973 / PF a928e733.
- Do not edit SAP/MES/WMS integration implementations, shared integration configuration, user materials, other branches or production data. No Nginx commands. Browser acceptance is user-owned.
- Admin means current request Actor.configuration_admin. Ordinary manufacturing members receive403 before source I/O; anonymous401 is host-owned. Keep private/no-store and scope checks for snapshots/downloads.
- Exactly nine GET routes under `/api/v1/manufacturing/workflow/production-tools`: `/status`, `/projects`, `/projects/{source_project_id}/status`, `/observations`, `/catalog/{kind}`, `/evidence`, `/evidence/{source_log_id}/content`, `/statistics`, `/snapshots/{snapshot_id}` (last seven relative to source-project path).
- Source IDs are decimal strings matching `[1-9][0-9]{0,19}`. Source directory is `projuectlists`, selected columns `id,name`, `del=0`, id descending,100 entries plus one sentinel. New statements must join the exact registry.
- Private config version2 has source_namespace/revision/mysql?/questdb?/objects?/object_prefixes; no dataset_id or bindings. Factory `build_native_config(config_path,snapshot_path)` and module `NATIVE_PRODUCTION_PROTOCOL=2`.
- Scope dataclass is SourceScope(source_namespace,source_project_id,revision,object_prefix), no manufacturing UUID. ProductionToolsConfig(source,source_namespace,revision,object_prefixes,snapshot_path). Service `ProductionToolsService(config, *, clock)` has no WorkflowStore.
- Independent v2 snapshot schema, source namespace/project/revision/prefix fingerprint; no manufacturing dataset. Keep1000rows/2MiB capture,100page,100live snapshots per source project,24h retention,10MiB downloads,31-day maximum range and existing bounded source timeouts/concurrency. Reject v1 caches; no automatic migration.
- Never print credentials, private endpoints, raw source rows or object contents; never commit analysis-repos or private files. Existing production source config is disabled, workflow datasetdemo/schema24. No mock cleanup or business fact projection.
- Use `/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python` with `PYTHONPATH=src` and `TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform/.worktrees/native-production-tools-20261110`; scoped tests first, retain first failures and narrow reruns. Final review uses most capable model.

### Task 1: Independent source service, configuration, snapshot and HTTP contract

**Files:** `src/manufacturing_platform/production_tools/{contracts,queries,source,transports,store,service,api}.py`, `src/manufacturing_platform/{__init__,workflow/api}.py`, `tests/production_tools/`, `scripts/verify_production_tools.py`, `docs/runbooks/native-production-tools.md`.

**Interfaces:** Implement the exact contracts in Global Constraints. `NativeProductionSource.projects(*,before_id=None)` returns the source directory page; `.project(source_project_id)` checks one active project. Service `.projects(actor, *, before_id=None)`, `.status(actor, source_project_id=None)`, `.query(actor, source_project_id, query)`, `.snapshot(actor, source_project_id, snapshot_id, *, offset=0,limit=50)`, `.evidence(actor, source_project_id, source_log_id)` expose admin-only reads. Keep existing query fields/row semantics. Public status/page use source_namespace/source_project_id, no manufacturing project_id.

- [ ] Add a failing independent admin API regression with zero manufacture projects, using real FastAPI route/SQLite snapshot path and fake transport boundary only:

```python
response = client.get('/api/v1/manufacturing/workflow/production-tools/projects', headers=admin)
assert response.status_code == 200
assert response.json()['items'] == [{'id': '7', 'name': 'Source seven'}]
assert client.get('/api/v1/manufacturing/workflow/projects', headers=admin).json()['items'] == []
```

Run `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/production_tools/test_standalone.py`; retain RED output (old router404).

- [ ] Replace manufacturing binding contracts by SourceScope/configv2; add registered directory statements, directory normalization/ordering and bounded error behavior. Implement admin-only service, v2 source-bound snapshots and nine handlers; validate snapshot isolation against workflow paths in router initialization. Do not retain old project-bound production routes or create compatibility bindings. Update existing native tests to the new authorization contract while preserving transport/cursor/precision assertions. Add active/deleted/unknown source projects, malformed IDs, list continuation and directory failure cases.
- [ ] Test denied ordinary member before transport calls, snapshot cross-project404, downgraded admin next request403, fingerprint expiry, no workflow table changes, unsupported capabilities, prefix/download bounds, strict configv2, rejecting legacy config/cache. Update socket regression to real host middleware and actual admin downgrade between requests, with no manufacture project setup requirement.
- [ ] Update safe CLI to `--source-project <decimal-id>` and remove manufacturing dataset/project options. Update runbook with real source project selection, configv2, separate snapshots and enabled limits. No credentialed queries in subagent work.
- [ ] Run `PYTHONPATH=src .../python -m pytest -q tests/production_tools tests/test_api.py --ignore=tests/production_tools/test_socket.py` once after focused GREEN (the native socket depends on PF Task3 whitelist and is mandatory at integration, not skipped or weakened); report passed/failed/errors/skips exactly. Run scoped Ruff if available and `git diff --check`; commit only owned paths. Report RED/GREEN, schema/version decisions and exact API JSON for frontend/host handoff.

### Task 2: Source-native UI and API client

**Files:** `webui/src/workflow/productionTools/{types.ts,ProductionToolsWorkspace.tsx,ProductionToolsWorkspace.test.tsx,productionTools.css}`, `webui/src/workflow/{api.ts,WorkflowApp.tsx}`, relevant API/navigation tests only.

**Interfaces:** Add `productionProjects({before_id?},signal?)`; existing production client methods take source_project_id string and build `/production-tools/projects/{id}`. Global status is `productionStatus(undefined,signal)`, scoped status passes ID. Source pages include source_namespace/source_project_id. Source directory page contract from Task1. Workspace receives api only, no manufacturing projects/initial manufacturing ID.

- [ ] Write focused failing tests: admin with zero manufacturing projects loads real source project names; ordinary member has no production navigation; selected source ID appears in all request paths. Run `cd webui && npx vitest run src/workflow/productionTools/ProductionToolsWorkspace.test.tsx` and retain RED.
- [ ] Replace manufacturing selector by source-directory selector and explicit list continuation; surface global unconfigured versus source error, no-rows and forbidden states. Keep abort/generation protections on directory + observation changes and clear old source data immediately. Retain four tabs, parent/version filters, time/SN filters, add device filter where already supported, statistics semantics, snapshot/cursor precision and scoped evidence URLs.
- [ ] Guard navigation/workspace using existing bootstrap configuration_admin; no bootstrap API grant widening. Update tests for pagination, directory failures, unknown/removed projects, big source IDs and ignored stale responses.
- [ ] Run focused Vitest GREEN, all normal Vitest once using existing exclude rules, `npx tsc --noEmit`, `npm run bundle`; retain exact outputs, no browser use. Commit owned files and report.

### Task 3: PF exact host routing and configuration protocol

**Files:** PF `backend/app/{manufacturing.py,manufacturing_paths.py}`, focused `backend/tests/test_manufacturing_*.py` that cover native routes/settings.

**Interfaces:** Task1 module exports NATIVE_PRODUCTION_PROTOCOL2 and two-argument factory. Host still supplies optional production_tools to build_workflow_router; preserve general workflow/legacy compatibility behavior. Replace the production route whitelist by nine independent exact GET paths; no new mounts or environment key names.

- [ ] Write failing host regression: new independent GET is resolved through real manufacturing auth; ordinary member denied by MF consumer, anonymous401; old production path is not allowed. Exact route set comparison must explicitly name all nine new entries.
- [ ] Gate native compatibility on protocol2 and callable two-argument factory. Call `build_native_config(config_path,snapshot_path)` without manufacturing dataset; preserve private path/alias guards and sanitized unavailable isolation. Keep unknown routes, methods and malformed IDs closed through host/consumer contracts; do not loosen general matcher.
- [ ] Run the existing four focused manufacturing host groups using PF baseline venv and `TEST_PLATFORM_SOURCE_ROOT` selecting this PF checkout. MF linked tests select the Task1 source. Run scoped lint/diff and commit only owned PF paths; report compatibility, test output and review package inputs.

### Task 4: Integration, mainline and real-data acceptance (root)

**Files:** current design/plan/runbook links and a new verification receipt; immutable private verification inputs. No shared SAP/MES/WMS code.

- [ ] Review every task with a fresh task reviewer, fix all Critical/Important findings, then request whole-branch review with exact MF/PF diffs and unresolved Minor ledger.
- [ ] Verify merged native/general API and PF host tests, frontend checks and real-socket acceptance; retain any first failure. Review all changed interface consumers and explicit whitelist updates. Assert workflow schema24 and existing business content unchanged.
- [ ] Refresh mainline/working trees before merge so the parallel SAP/MES/WMS session is preserved. Merge reviewed MF/PF branches without overwriting other changes; commit/push development receipt separately from deployment state.
- [ ] Using existing private real connection settings, build configv2 without local synthetic UUID bindings. Run bounded actual directory/catalog/observation/statistics/OSS reads and real protected HTTP through current host using isolated test identity only for local acceptance. No source writes and no mock fallback. Keep raw records out of Git.
- [ ] Carry authorized production enablement forward using the existing release controller and exact current runtime baseline. If no further release is performed, explicitly report development/real-read acceptance separately and identify remaining production enablement. Do not claim production success from local tests.
