# Final handoff polish and evidence report

Status: DONE
Code SHA: `14ec14bc74c05a5ba9814ff58a345c85fc036bc2`
Code commit: `fix(ui): retain project handoff status filters`
Documentation/head SHA: `40db85e4abeb7ad3c09d7cf95601d18f70b4c853`
Documentation commit: `docs: record final handoff filter validation`
Worktree: `/Users/neo/.codex/worktrees/a065/AI-Manufacturing-Platform`
Review input: `.superpowers/sdd/final-review.md`.

## Change and scope

The final review had no Critical or Important issue, and one new Minor: a project-local disputed/all filter reset to pending after a detail unmounted its workspace. Added a closed MaterialHandoffFilter union and a project-ID-keyed filter map in WorkflowApp. Supply forwards the selected project's filter and setter to MaterialHandoffWorkspace. The workspace uses parent context when supplied and retains its existing local fallback for standalone uses. Its filter does not affect the separately stored global ledger context. An unseen project defaults to pending.

The new real HTTP cases cover disputed and all filters through record detail → return, direct related-lot → return, accepted dirty-guard epoch remount and switching back to handoff mode. They also verify that the global pending filter remains independent and a different new project starts at pending. Existing direct-row receive/resolve/cancel/lot, newly created project detail chains and global detail/action/filter tests remain in the same focused run.

The code commit contains exactly five explicit code/test paths:

- `webui/src/workflow/materialHandoffTypes.ts`
- `webui/src/workflow/MaterialHandoffWorkspace.tsx`
- `webui/src/workflow/SupplyWorkspace.tsx`
- `webui/src/workflow/WorkflowApp.tsx`
- `webui/src/workflow/materialHandoffHttp.test.tsx`

After committing code and recording CODE_SHA, E30 was executed at that actual HEAD. The following separate documentation-only commit changes exactly `docs/oem-material-handoff-iteration-2026-11-03.md`, updating the current code reference, project filter outcome and precise frontend/bundle/E30 evidence while preserving the backend reuse and visual limitations, inherited debt and unique delivery archive. No supplemental patch, user-dirty source document, shell component, legacy HTTP test, backend source/test, preview file or node_modules path was changed/staged by this wave.

## RED

```sh
cd webui
WORKFLOW_TEST_PYTHON=/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python npm test -- src/workflow/materialHandoffHttp.test.tsx --reporter=dot
```

Observed before implementation: **2 failed, 5 passed**, 3.29s. Disputed returned as 待接收 instead of 待处理差异; all returned as 待接收 instead of 全部记录. Both failures occurred at the actual post-detail filter assertion. Durable log: `.superpowers/sdd/final-fixes-red.log`.

An intermediate assertion was scoped to the handoff table after the administrator's project-progress table also rendered rows. This was a test selector correction; the production filter assertion already passed after the context fix.

## GREEN

```sh
WORKFLOW_TEST_PYTHON=/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python npm test -- src/workflow/materialHandoff.test.tsx src/workflow/materialHandoffHttp.test.tsx --reporter=dot
```

**2 files, 28 tests passed**, 3.63s: 21 component/navigation and 7 real authenticated HTTP tests. No warnings. Durable log: `.superpowers/sdd/final-fixes-focused.log`.

```sh
WORKFLOW_TEST_PYTHON=/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx --reporter=dot
```

**31 files, 301 tests passed**, 14.08s. Existing warnings are confined to formHttp/oemFormsHttp; the handoff tests remain clean. Durable log: `.superpowers/sdd/final-fixes-frontend.log`.

```sh
npm run test:bundle
```

TypeScript, Vite, IIFE global and scoped CSS checks passed. **483.75 kB JS / 141.40 kB gzip**, Vite 512ms. Durable log: `.superpowers/sdd/final-fixes-bundle.log`.

The above required checks passed before the explicit code commit; its source is exactly the verified state. No further frontend test rounds or changes followed.

## E30 at the committed code SHA

At actual HEAD `14ec14bc74c05a5ba9814ff58a345c85fc036bc2`, repository root:

```sh
TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform WORKFLOW_ACCEPTANCE_CASES=E30 PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python -m pytest -q tests/workflow/test_acceptance.py::test_e30
```

**1 passed in 2.85s**. `.superpowers/sdd/final-e30.log` records the actual execution SHA, exact command and raw pytest output. No backend suite was rerun.

Backend unchanged-code verification:

```sh
git diff --exit-code 850b53b..14ec14bc74c05a5ba9814ff58a345c85fc036bc2 -- src tests
```

Exit **0**, empty output. The approved **92 passed, 25.63s** backend result was executed at `850b53b`; last backend change was `10bc873`. Its reuse through CODE_SHA is explicitly documented as unchanged-code evidence, not a backend rerun at CODE_SHA.

## Documentation validation and separate commit

After editing only the designated iteration document:

```sh
node .superpowers/sdd/task-3-doc-validate.mjs
```

Passed: **107 GFM tables, 44 Mermaid diagrams, 64 local links**, no errors, no baseline/current broken links, and prior source-document identifiers preserved. Output: `.superpowers/sdd/final-fixes-doc-validation.log`; structured result: `.superpowers/sdd/task-3-doc-validation.json`. The existing adapted validator was reused without changes. `git diff --check` and each staged diff check passed.

The delivery document continues to identify `.superpowers/sdd/oem-handoff-2026-11-03/` as the controller's unique archive destination, preserving unrelated original reports. It retains visual acceptance at `c9ebc6b`, including desktop/390×844 coverage and the limit that receipt/discrepancy/cancel submission was tested by HTTP rather than visually. No fresh visual review or production integration is claimed.

## Retained inherited debt and follow-up

1. The shared-shell account name is truncated on the narrow viewport. Full identity remains available in record facts; no handoff control was blocked in the supplied visual evidence. Track a shared-shell identity disclosure/layout improvement separately. No shell refactor was attempted here.
2. Existing formHttp/oemFormsHttp act warnings remain validation noise. Track their asynchronous test-boundary cleanup separately; neither new handoff test emits warnings. No unrelated legacy-test rewrite was attempted.

## Self-review

The project filter is a closed, presentation-only value keyed by project ID. It survives workspace/details unmounts and the existing dirty-dialog epoch remount without changing command fields, permissions, facts or operation lifecycle. Global ledger state remains separate, new projects default to pending, and the real HTTP tests prove both visible filters and retained rows. Existing origin callbacks remain unchanged. No backend or supplemental document delta was altered. After E30, the only committed change is the designated documentation update, so executable source remains CODE_SHA. No unresolved new correctness concern found; the two inherited debt items above remain candidly documented for follow-up.
