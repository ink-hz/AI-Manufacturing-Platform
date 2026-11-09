

## E29 full-suite dependency failure — 2026-11-09

Baseline: `d40e6ea` (runtime `d186493`); worktree `/Users/neo/.codex/worktrees/814b/AI-Manufacturing-Platform`.

### RED: focused traceback before changes

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q 'tests/workflow/test_d3_authorization.py::test_actual_host_e29_records_scope_write_matrix[standalone]' -x
```

Exit 1: `1 failed in 6.99s`.

The traceback reached `tests/workflow/d3/case_authorization.py:243` after the actual-host authorization, denied-write snapshots, trusted-admin accounting, policy and historical bootstrap proofs. The failure was `tests/workflow/d3/proof_support.py:59`, `assert process.returncode == 0, "D3 component proof failed"`.

Recorded subprocess stderr supplied the root cause:

```text
Error: Cannot find module '/Users/neo/.codex/worktrees/814b/AI-Manufacturing-Platform/webui/node_modules/vitest/vitest.mjs'
code: 'MODULE_NOT_FOUND'
Node.js v26.5.0
```

Evidence: `/private/var/folders/f2/_6ql657j53ddvq65fsm6m_tw0000gn/T/pytest-of-neo/pytest-16961/test_actual_host_e29_records_s0/run-20261109T104157-2e483298cc7046d58d7f2ae91c5f96d8/E29/000213-d3-ui-process.json`.

### Root cause and setup repair

The isolated worktree had only partial ignored frontend dependencies. Vitest was absent. This was worktree setup, not a production regression, schema drift, explicit inventory mismatch or historical fixture expectation. No production code, tests, authorization assertions, inventories, runner, original dependency directory or raw materials were edited.

Executed in worktree `webui/`:

```sh
npm ci --no-audit --no-fund
```

Exit 0: `added 81 packages in 900ms`. Dependencies were installed locally from the existing worktree `package-lock.json`; no tracked manifest/lock change. npm emitted the existing whatwg-encoding deprecation and allow-scripts pending notices for esbuild/fsevents. The original checkout dependency directory was untouched. This completed before the root's subsequent instruction proposing dependency links; local lockfile installation already provided all dependencies, so no additional symlinks were introduced.

### GREEN: both exact authorization cases, with real component proof

```sh
PYTHONPATH=src TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_d3_authorization.py -x
```

Exit 0: `2 passed in 16.89s` (standalone and preexisting-projects).

Both generated `e29-retired-vitest.json` reports have `numPassedTests=37`, `numFailedTests=0`, `numTotalTests=37`, `success=true`:

- `/private/var/folders/f2/_6ql657j53ddvq65fsm6m_tw0000gn/T/pytest-of-neo/pytest-16962/test_actual_host_e29_records_s0/run-20261109T104237-8ce81cc3119f49799db5ee7c546cf64c/E29/e29-retired-vitest.json`
- `/private/var/folders/f2/_6ql657j53ddvq65fsm6m_tw0000gn/T/pytest-of-neo/pytest-16962/test_actual_host_e29_records_s1/run-20261109T104246-5c5cf7341aa04bc5bf0ac593cb876a57/E29/e29-retired-vitest.json`

`git status --short` is clean after setup. No feature fix commit is warranted for ignored dependencies; no full-suite run was started by this worker. Root retains final full-suite rerun responsibility.
