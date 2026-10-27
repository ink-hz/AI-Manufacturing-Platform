# Consolidated final-review fix wave

Status: DONE. Implementation commit `eb9a2f257193ac3ad194cbd27208be212296a29b`, based on `5b79f1b4c0c0f42e1c7efc459fce79fbac579597`. This report is committed separately so it can identify the exact implementation SHA.

## Four findings resolved

1. Added `manufacturing_task_sources`, keyed by stable project/task IDs and referencing readiness/item IDs. All project save paths persist links within the existing transaction and serialize task JSON without `source`, using copied response structures. `_read` and `_all` enrich current projections; get, project-task list, dashboard and update responses retain source navigation. Ordinary task receipts retain the old shape, while current replay adds `source:null`. Existing inline source references remain readable and migrate into the link table on aggregate saves. Old writers leave the additive table untouched. No API fields or routes changed.
2. Creating mandatory readiness with no mandatory items now returns 422 before fact/event/receipt persistence. The client gives plain Chinese guidance before POST. Both correcting item applicability and explicitly choosing an optional record work through the existing request-reset flow. Optional readiness does not block completed projects.
3. Selected system details show scoped authority/object type, business line, entry point and unfinished handoffs (draft/sent/returned) to that system. Authority and exact source-project handoff navigation use the existing dirty guard. Context remains outside disabled editing controls, including read-only and failed/frozen forms. No names or business facts are invented.
4. Send and receive actions both mark evidence and event time required. Empty send does not POST; completed send retains existing local-time-to-UTC conversion and expected version.

## RED and focused GREEN

Commands run from the manufacturing worktree unless noted:

- `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/test_final_review.py`
  - Initial RED: 5 failed, 1 passed. Actual archived old code failed with `ProjectDetail` validation errors on `tasks.*.source`; required/all-optional creation returned 200 instead of 422. Three atomic-table tests initially exposed the absent normalized table.
  - Test harness corrections after the first implementation: supply all required fields to the real old stage writer; assert the private router's 503 storage response instead of expecting its caught SQLite exception. These did not change production behavior.
  - Final focused GREEN: **7 passed**. Additional coverage proves old/current creation receipt replay and preservation of existing inline source references.
- From `webui`: `npm test -- src/collaboration/product.test.tsx -t 'all optional checks|selected-system|independent send'`
  - Initial RED: **5 failed**, reproducing empty send POST, mandatory/all-optional POST, and missing selected-system context.
  - Expanded editable/read-only/frozen context coverage detected a nested dirty guard in the new handoff navigation; the final handler delegates to the existing guarded parent navigation once. Asynchronous destination assertions wait for the actual handoff detail.
  - Final focused GREEN: **6 passed**, 41 skipped. Readiness correction follows the existing explicit reset flow; prior NA reset/attestation semantics remain unchanged.

## Actual source compatibility proof

Trusted fixture: `tests/fixtures/manufacturing-161292be.tar.gz` (13,429 bytes).

- Unmodified Git source from deployed commit `161292be7c01038cc7c25b5f36aea04577c19823`.
- Exported with `git archive <commit> src/manufacturing_platform`, compressed deterministically with gzip mtime=0.
- SHA256: `ae37d3d9ef165408616aeb8ee08a99c812a2acd6764d6308031ba82a3ddd6fea`.
- Provenance is recorded alongside the fixture. Test checks pinned digest, rejects absolute/traversal/non-regular archive entries, and uses safe extraction. No network, new dependencies, private business data or altered mock old schema.

The portable regression creates a legacy project/task with actual old source, then uses real current HTTP to create an ordinary new project/task and linked readiness issue, and performs core/stage/task writes on legacy data. Actual old `ProjectRepository.get`, `list`, `dashboard`, ordinary-task receipt replay, task update and stage update run against that SAME disposable SQLite database. Current HTTP then reads forward with the correct original source, updated task status, unchanged durable controls/history and blocked readiness aggregate. Flat task and dashboard source projections agree. Raw task JSON contains no `source` key; normalized links remain. Tests also inject failures independently at link, event and operation inserts and verify no task/link/audit/receipt survives, then retry the same UUID successfully once.

## Final verification

A single final pass was split by suite directory, with no repeated passing full suites:

- `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests` — **206 passed** (199 existing + 7 new), 8.60s.
- `PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q deploy/tests` — **54 passed**, 0.69s. This includes two concurrent root-owned deployment tests; the original deployment baseline was 52.
- Total observed backend: **260 passed** = original 251 + this wave's 7 + root's 2.
- From `webui`, `npm test` — **127 passed**, 7 files (122 existing + 5 new).
- From `webui`, `npm run test:bundle` — TypeScript, Vite build and IIFE/scoped-CSS validation pass; 59 modules, JS 292.51 kB, CSS 17.68 kB.
- `git diff --check` — clean. Implementation diff against baseline has no changes to docs, knowledge or handbook code/source. No new dependencies.

## Preserved boundaries and handoff

All prior source navigation, read-only multi-item navigation, mounted CAS baseline, strict pending version bindings, independent fresh NA attestation and receiver history tests pass. Existing authorization/CSRF/no-store and UUID/CAS behavior is unchanged. No platform edits, production writes, browser automation, merges or deployment. Existing source handbook was not modified.

Root-owned concurrent `deploy/candidate_verify.py`, `deploy/release.py`, and `deploy/tests/test_candidate_previous_source.py` remain outside this implementation commit. Existing untracked `webui/node_modules` is untouched. Root owns review, exact-source build/candidate verification, merge and deployment.

Remaining issues within this four-finding scope: none. Deliberate limit: candidate-era inline sources are preserved on reads and normalized when their aggregate is next saved; this is not a production-wide rewrite of untouched candidate databases. Newly generated project JSON is rollback compatible immediately.
