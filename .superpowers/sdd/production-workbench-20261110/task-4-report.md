# Task 4 implementation and verification report

Status: implementation complete; ready for independent Task 4 review. No merge, deployment, browser or final whole-branch review performed by this agent. Root retains those gates. Public verification and specification status now distinguish implemented branch code from acceptance/deployment.

## Worktrees and commits

- MF cwd for every MF command: `/Users/neo/.codex/worktrees/6f75/AI-Manufacturing-Platform`, branch `codex/production-test-workbench`, baseline `440ec28`. Product/test commit: `990ea879d2cb1c655012049a62bcacfe3d7bf8cc`; documentation/report are the following delivery commit.
- PF cwd for every PF command: `/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform`, branch `codex/production-test-workbench-host`, baseline `57060de1`. Product/test commit: `f8f362596ed81cac8360c0aa202acb545509ea21`.
- Initial PF tree clean. MF only had untracked `webui/node_modules` symlink; never staged. Original user roots/materials untouched. Read PF `AGENTS.md` and the task brief/interface/root evidence before editing. Applied TDD, verification-before-completion and systematic-debugging skills. No subagents spawned.

Explicit owned files:

| Repository | Files |
| --- | --- |
| MF code/tests | `src/manufacturing_platform/production_tools/investigation_models.py`, `src/manufacturing_platform/production_tools/investigations.py`, `tests/production_tools/test_investigations.py`, `tests/production_tools/test_socket.py` |
| MF documentation | `docs/verification/production-test-workbench-2026-11-10.md`, `docs/superpowers/specs/2026-11-10-production-test-workbench-product-design.md`, this report |
| PF | `backend/app/manufacturing.py`, `backend/app/manufacturing_paths.py`, `backend/tests/test_manufacturing_production_tools.py` |

No shared identity middleware or authorization service implementation changed. Only the existing manufacturing registry gained 12 exact operations. Unknown paths/methods and unrelated business authorization retain their existing checks.

## Contract corrections and concrete proof

1. `InvestigationContext.history_sn` is optional strict `Text` (1–200), independent of `sn`, history range, primary consistency and impact filters. Unknown fields remain forbidden. Tests prove direct history with no primary through actual HTTP save/handoff/fork, original `sn` unchanged, existing primary still checked, invalid types/bounds rejected, and history/note updates retain frozen impact without source reaggregation.
2. Comparison context validation now additionally skips only `software_version`, `config_log_id`, `config_version` for exact and missing-field symptom constraints. It retains stage/tool/order constraints and all main/project/source safeguards. Unit regressions prove exact A vs B and missing vs present, unchanged saved context, update persistence, contradictory primary rejection and wrong stage/tool comparison rejection. Actual HTTP saves both different-version and missing-version comparisons.
3. Both resolve endpoints return required output-only `binding={kind,id,version,primary_selection_id,comparison_selection_id}`. Values derive from the exact payload passed into `_resolve`; no second revision read labels the result. Unit test updates the draft during selection resolution and proves the response remains bound to that original payload, then resolves the new null-primary revision. HTTP reads metadata version 1, updates from another tab to version 2, and resolves version 2; stale update is 409. Handoff binding remains at its fixed version after A updates the personal draft. Client `binding` input is rejected with 422.
4. PF registry equals all actual released native method/path pairs: 21 total (17 GET,3 POST,1 PUT). Fallback reservation now uses `(method,path)` rather than just path. A partial native release supplying GET investigation list/detail but omitting POST/PUT keeps those GETs reachable; absent writes remain authenticated, CSRF/Origin protected and private 503. Old/incompatible releases and whole-workflow absence remain contained.
5. Production fallback invokes current administrator authorization with no-store, preserving hard-stale readonly writes. Initial implementation classified actual URL text; a regression showed ordinary member GET `/workflow/projects/1/systems/erp/facts/production-tools/object` incorrectly became403. Fixed classification to `request.scope['route'].path.startswith(MANUFACTURING_PREFIX + '/workflow/production-tools/')`, so dynamic values cannot change namespace policy. That exact unrelated workflow fallback now retains503 instead of a new admin restriction. No auth/middleware files changed or business checks relaxed.
6. Host validates both snapshot and derived `snapshot_path+'.investigations.sqlite3'` before calling the two-argument native factory. Derived path is checked against legacy/domain/authority/snapshot/config; tests cover direct, symlink and hardlink aliases. Optional failure leaves unrelated workflow available. Native protocol2/factory arity/old5-position constructor retained; no custom path feature.

## RED, intermediate failures and GREEN

All logs below are local ignored test evidence under `.superpowers/sdd/production-workbench-20261110/`; they remain on disk. This report preserves the failures as well as final results.

| Log | Result and interpretation |
| --- | --- |
| `task-4-native-red.log` | 4 failed,27 deselected: exact/missing comparison `SOURCE_INVALID_QUERY`422, `history_sn`422, and resolution `KeyError: binding`; intended missing behaviors |
| `task-4-host-red.log` | 19 failed,15 passed: actual registry differs; enabled config guard expectation and15 derived aliases not isolated; partial mixed methods and admin unavailable contract fail |
| `task-4-native-green.log` | 4 passed,27 deselected in0.25s after narrow fixes |
| `task-4-host-green-attempt.log` | 32 passed,2 failed in1.57s; new write tests used invented CSRF token rather than existing FakeAuth token |
| `task-4-host-green.log` | 1 passed,1 failed,32 deselected in0.82s after using `auth.csrf`; remaining readonly GET expected access200 but got503 |
| `task-4-socket-attempt.log` | Initial real socket journey1 passed,1 deselected in2.61s; later expanded version-missing/direct-history assertions covered by final447 run |
| `task-4-native-covering.log` | 447 passed in13.48s;0 skips/warnings; stable final MF code/tests |
| `task-4-host-covering.log` | First four-suite run219 passed,1 failed in11.24s; same readonly fixture assertion, retained rather than replacing evidence |
| `task-4-host-isolation-red.log` | 2 failed,33 deselected in0.67s: readonly response was `required audit unavailable` (existing FakeAuth lacks readonly audit); unrelated dynamic object URL wrongly denied403 by new substring classification |
| `task-4-host-isolation-green.log` | 2 passed,33 deselected in0.63s after adding an explicit synthetic audit boundary and using canonical registered route path |
| `task-4-host-final.log` | 221 passed in11.04s;0 skips/warnings after the actual host correction; final four-suite run justified by new product change plus prior failure |

Readonly fixture investigation traced middleware's existing mandatory `hard_stale_audit` call before dispatch. The added test-only synthetic audit callback permits reaching the intended handler; the test asserts the specific `Workflow unavailable` response for readonly GET, verifies readonly POST503 and `/access`200. The real socket fixture likewise explicitly supplies a synthetic audit callback, with successful readonly handoff GET and denied writes. No production audit requirement was weakened.

## Exact test commands

MF commands ran with cwd `/Users/neo/.codex/worktrees/6f75/AI-Manufacturing-Platform`; PF commands with cwd `/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform`. The PF worktree `.venv` supplied Python and installed checked-in backend dependencies including native SDKs. Output redirections selected the logs above; no private config output.

MF native RED then GREEN (same command twice):

```sh
PYTHONPATH=src /Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform/.venv/bin/python -m pytest -q tests/production_tools/test_investigations.py -k 'comparison_retains or history_subject or resolution_binding'
```

Initial host RED and first host GREEN attempt (same command):

```sh
TEST_MANUFACTURING_RELEASE_ROOT=/Users/neo/.codex/worktrees/6f75/AI-Manufacturing-Platform PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_manufacturing_production_tools.py
```

Targeted host fixture follow-up:

```sh
TEST_MANUFACTURING_RELEASE_ROOT=/Users/neo/.codex/worktrees/6f75/AI-Manufacturing-Platform PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_manufacturing_production_tools.py -k 'partial_release or unavailable_production'
```

Initial socket journey:

```sh
TEST_PLATFORM_SOURCE_ROOT=/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform PYTHONPATH=src /Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform/.venv/bin/python -m pytest -q tests/production_tools/test_socket.py -k handoff
```

Stable MF covering (once):

```sh
TEST_PLATFORM_SOURCE_ROOT=/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform PYTHONPATH=src /Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform/.venv/bin/python -m pytest -q tests/production_tools tests/test_api.py
```

Host isolation RED then GREEN (same command twice):

```sh
TEST_MANUFACTURING_RELEASE_ROOT=/Users/neo/.codex/worktrees/6f75/AI-Manufacturing-Platform PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_manufacturing_production_tools.py -k 'unavailable_namespace or unavailable_production'
```

PF four-suite covering (first retained219/1, final stable221/0):

```sh
TEST_MANUFACTURING_RELEASE_ROOT=/Users/neo/.codex/worktrees/6f75/AI-Manufacturing-Platform PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/test_manufacturing_bridge.py backend/tests/test_manufacturing_workflow_bridge.py backend/tests/test_manufacturing_member_profiles.py backend/tests/test_manufacturing_production_tools.py
```

`git diff --check` passed in both worktrees before product commits and again for docs. Test formatting used black26.10.0 installed only under `/tmp/production-workbench-task4-format`, not repository dependencies. Pip emitted its routine update notice; no pytest warnings. Expected sanitized denial/config warnings were captured in negative tests, with no private settings/source payload output.

## Real HTTP boundary and separate live-source evidence

`tests/production_tools/test_socket.py::test_real_socket_admin_handoff_revision_history_and_expiry_journey` starts three real uvicorn processes across durable storage restarts. It exercises actual PF identity middleware, cookie authentication, current roles, authorization registry, CSRF/Origin and `no-store`; synthetic session provider/auditor/clock and injected registered native fixed-SELECT reader/object provider are explicit boundaries. It directly includes MF workflow router; independent PF suites cover release loading and exact host contract. This is real local HTTP/process proof with synthetic identities/source, not real-source, employee login or production acceptance.

The source reader receives only registered native statements; tests retain repeated events, correctly filter exact temporal locators, and synthesize a duplicate after24h snapshot expiry. AdminA→saved main+version comparison+logs→tab revision→immutable handoff→AdminB restore/fork→history roundtrip/impact invariance→snapshot ambiguity→downgrade403/revoked401→source revision change404→30day expiry410 all execute on real sockets. Ordinary/member/management viewer403; hard-stale admin reads succeed but mutation503; source revision changes do not disable unrelated `/projects`.

Root-run actual-source evidence is recorded in `root-acceptance-evidence.md`: at7d0b74c each Source-A/B17 cases/28 registeredSELECTs, and at83cad73 each11 impacted cases/27SELECTs. Includes sourceMIN time, exact missing predicates and positive complete31-day FAIL groups on both; narrow missing cohorts empty, so no positive missing-cohort claim. No SQL changed in Task4, so per instruction no repeat live reads. Source business writes0, no oldGo initialization, externalmessages, privateconfig/source rows/IDs/URLs output or browser/deployment.

## Frontend evidence, delivery and remaining gates

Reused Task3 final5-file84 focused component PASS and TypeScript/Vite/IIFE bundle PASS at6aef6f5; no agent repeat. Root subsequently reported current combined generic frontend37files/391tests PASS29.07s,no warnings/skips atMF990ea87/PFf8f36259. Root-run command (cwd MF/webui):

```sh
WORKFLOW_TEST_PYTHON=/Users/neo/.codex/worktrees/production-workbench-host-20261110/AI-Agent-Platform/.venv/bin/python npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx
```

E30 explicitly excluded/unexecuted, not counted as passed. Real employee login/roles, browser/page acceptance and production business/deployment acceptance remain unexecuted. No whole-backend rerun outside affected production/API scope is claimed. Version-combination board remains later scope.

Root must independently review Task4, perform final whole-branch review, resolve Critical/Important findings, then handle mainline integration and exact merged main-root bundle/targeted merged verification. This agent has not merged, deployed or conducted those reviews. Product heads remain fixed after the green covering suites; following changes are documentation only. Remaining concerns: required external acceptance gates above, not a blanket usability claim.


Documentation check note: an initial link sweep over the entire existing approved specification stopped on the pre-existing ignored private analysis reference `../../../analysis-repos/shengchanggongjuguanli/public/databases/tables.go`, absent in this isolated checkout. No existing source-analysis links were changed or private files copied. The subsequent scoped check of all new verification-document links and the added specification→verification link passed. Product evidence remains unchanged; `git diff --check` passed. Documentation delivery commit `8fc99ef8643a800b8621c7eba58b0297173e4c46` follows MF implementation `990ea87`; this appended note records the check limitation transparently.
