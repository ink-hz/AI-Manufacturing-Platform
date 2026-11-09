# Task 1 report — milestone validity and expedite responsibility tasks

Status: DONE. Scope: Task 0 + Task D of `docs/superpowers/specs/2026-11-09-oem-expedite-batch2-tasks.md`, design §3.2, and `.superpowers/sdd/task-1-brief.md`.

## Changes

- `src/manufacturing_platform/workflow/expedite.py`: arrival milestones now use only each observation's latest match. Handoffs must have the case's explicit work order, state received/resolved, and positive actual received quantity. Both segments select the earliest actual event instant using aware datetime comparison, preserving original timestamps and subsecond precision.
- `src/manufacturing_platform/workflow/service.py`: open OEM expedites join the existing SQL responsibility UNION with its shared `ORDER BY category,id LIMIT 51`. Current warehouse/supply/production/project_owner roles determine eligibility; every returned target goes through `_actions`, and actionless targets are excluded. Existing 50-row/truncated handling, responsibility ordering, handoff tasks, readiness tasks, and duplicate suppression remain in use.
- `tests/workflow/test_expedite_tasks.py`: 14 regression cases (including parameterization) cover current arrival rematches, timezone/insertion ordering, other/no work order, zero actual receipt including resolved zero, unresolved discrepancies, valid positive resolved handoff, open-case visibility before receiving/IQC, production/supply title transition, other roles' general title, rejected-only IQC, trusted source correction from positive accepted quantity to zero, role revocation/read-only/outsider behavior, closure, 50/51 pagination, SQL project/limit/effective-view boundaries, and existing handoff responsibilities.

The general title is `急料待跟进`. Positive effective IQC quantity changes only the same task's title for supply/production to `急料已检验，待安排上线/关案`. The task remains attached to its original expedite and does not assert inventory availability or putaway.

## TDD evidence

RED command (before production changes):

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_expedite_tasks.py
```

Output: `13 failed in 4.76s` (captured at `/tmp/expedite-task1-red.log`). Expected failures: old requirements retained a rematched arrival; other/no-work-order, zero/resolved-zero, and disputed handoffs supplied handoff milestones; insertion order overrode earlier timezone-aware event instants; open cases had no responsibility tasks; qualified/general titles were absent; the task page returned 1 existing readiness row instead of the expected 50 responsibility rows. Two initial fixture construction errors (duplicate scoped requirements and overallocating an existing formal order) were corrected before the recorded RED run. No production changes were made before observing these failures.

GREEN command:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_expedites.py tests/workflow/test_expedite_tasks.py tests/workflow/test_material_handoffs.py tests/workflow/test_progress.py
```

Output: `72 passed in 22.05s`, exit 0 (captured at `/tmp/expedite-task1-green.log`). `git diff --check` for the production files: clean. An initial broader command named a nonexistent `test_actor_tasks.py`; pytest collected no tests for that command, then the corrected command above ran successfully.

## Review and constraints

Self-reviewed production diffs against Task 0+D and the design. Parent requested to include this theme in final branch review; no additional subagents were spawned. Regression snapshots compare inventory, receipt, IQC, reservation, requirement, consumption/source-correction facts and all authority tables around expedite transitions and task/milestone reads. The source-correction test changes IQC only through the already-authorized source reconciliation pipeline, then snapshots it before the task reads.

No schema changes (version remains 24), registrations, inventory/IQC/reservation/requirement/accounting writes, frontend, adapter, issue-mark, mes.shortage, or L3 work were introduced in this task. No pushes or deployments. Unrelated worktree changes were excluded from this theme's commit.

Concerns: none blocking. Milestone selection streams all matching facts for the case's requirement rather than imposing an arbitrary fact cap, so the earliest instant stays correct; responsibility rows remain SQL-bounded. Full-suite verification and socket HTTP walkthrough belong to the parent task.

## Follow-up — deterministic original-receipt fixture

The broader Task2 run exposed a nondeterministic fixture: the rematch regression selected any receipt in the project after constructing a second requirement's receipt. Fixed only `tests/workflow/test_expedite_tasks.py`: the receipt helper now requires the setup commitment ID, filters by both project and commitment, and orders by created_at/id with LIMIT 1. Every arrival call passes `extras['id']`; all business assertions are unchanged.

Validation command:

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_expedite_tasks.py
```

Result: `14 passed in 5.73s`, exit 0; log `/tmp/expedite-task1-fixture-green.log`. No production changes or full-suite rerun. This follow-up report stays under the ignored expedite-batch2 path; historical generic reports remain untouched.
