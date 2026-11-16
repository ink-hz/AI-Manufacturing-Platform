# Task1 implementation report

- Branch: `codex/branding-v2-20261116`, isolated `.worktrees/branding-v2-20261116`.
- Base: `b313c37b186d2d7302f1df328bb305037f38e90e` (retains manufacturing/source UI fixes atop `25b0133`). Implementation head: the commit containing this report; exact SHA supplied in agent handoff.
- Production source reads/writes: none. No network, SSH, Docker, launchctl, browser or deployment actions. MES/WMS and SAP/MRP remain strictly read-only. Root's three dirty files untouched.

## Changes

Original approved v2 PNGs copied unchanged to `webui/public` and copied unchanged by Vite to dist. No image editing, generation, resize or dependencies. Full logo is framed on a white navigation panel; collapsed desktop navigation uses independent icon; mobile drawer restores full logo. Both accessible image names use 奥比制造管理. Images remain separate files, not inline JS.

Fixed same-origin URLs use configured API base plus `/workflow/assets/` and bootstrap release. Both existing legacy and workflow asset routes extend only the exact `master-logo-v2.png` and `app-icon-v2.png` media allowlists with `image/png`; existing authorization, release and path checks remain intact. Build artifact packaging now explicitly copies both PNGs so actual business releases include them and their manifest hashes.

PF local read-only inspection: `backend/app/manufacturing_paths.py` already permits GET `/assets/{asset_name}` for legacy/workflow routes. `webui/src/pages/ManufacturingPage.tsx` loads workflow assets from the same mount and release. No PF changes required for asset routing.

## Verification

- Red: API tests rejected new PNGs (12 expected failures); branding URL test initially failed; packaging test failed because new PNGs were absent.
- Green: `PYTHONPATH=src /opt/homebrew/bin/python3.11 -m pytest tests/test_api.py tests/workflow/test_a1_security.py deploy/tests/test_build_artifact.py -q`: **83 passed**.
- `npm test -- src/branding.test.ts src/console/branding.test.tsx src/index.test.tsx src/workflow/productionTools/visualCascade.test.tsx`: **12 passed**. Covers release-pinned path construction, unsafe origin/query paths, accessible name, navigation collapse, mount lifecycle regressions and CSS cascade regression.
- `npm run build`: TypeScript and Vite passed, no added dependencies. JS approximately 771 kB, CSS 77 kB; PNGs separate.
- Full `npm test`: **709 passed, 4 failed, 1 skipped**. `acceptanceNavigationHttp` requires externally supplied WORKFLOW_HTTP_BASE/SECRET/PROJECT_ID, absent in standalone run. `navigation` production badge assertion and two `materialHandoffHttp` filter-return assertions fail identically with the original HEAD ConsoleShell/console.css/WorkflowApp restored; confirmed baseline failures, not modified for this task.
- `git diff --check`: passed.

Original, public and dist hashes match:

| File | Bytes | SHA256 |
| --- | ---: | --- |
| master-logo-v2.png | 1087353 | baf0d7e26b5403853b62939787f689a8ec6351b2ef6259a8478861ead39e7778 |
| app-icon-v2.png | 1042109 | 23eb29fbbb9aa945ca9b190ec77e5dd4bb1c5cf61e68b3941b76b5a177587c8f |

## Review and limits

Parent independent review and actual release remain pending. No browser screenshot/employee-device small-size acceptance performed under this subtask's restrictions. PF sidebar entry still uses 大制造/Boxes and PF route title remains controlled by shared host. MF mount interface does not indicate the active host app, so document title/favicon were not changed: background/multiple mounts cannot safely own shared document branding. Changing those dedicated entry details requires separately scoped PF work; shared login/company branding must remain intact.

Optional local preview/candidate tooling still has JS/CSS-only inventories (`scripts/preview_manufacturing.py` ASSETS/prepare, `deploy/candidate_fixture.py` build_files). Actual production artifact packaging is updated; parent should extend those separate tooling inventories if using them to inspect the new branding. Parent should verify live response MIME, authorization, release pinning and actual PNG byte hashes after controlled publication.
