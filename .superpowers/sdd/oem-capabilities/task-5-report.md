# OEM capabilities — Task 5 integration and isolated preview report

Status: DONE for delegated implementation; parent owns final full regression, original36, whole-branch review, canonical integration and final preview launch. Base `d6bdae22acebf7e6755b56dd0ea634be8f0e972c`.

## Exact implementation scope

- `src/manufacturing_platform/workflow/progress.py`: adds only the existing `npi` readiness-check kind to S5 blockers. S2 and DTO shape remain unchanged; only explicitly linked NPI affects bulk qualification.
- `scripts/workflow_demo/oem_preview.py`: new shared, explicitly simulated two-project recipe; it does not invoke or reseed the existing six-project portfolio. Reuses existing Scenario prerequisites and Importer command orchestration without editing either.
- `scripts/preview_manufacturing.py`: exclusive new-directory preparation, manifest validation, fixed loopback server and guarded synthetic local administrator host using the real registered workflow router.
- `scripts/build_preview_renderer.mjs`: bundles the exact existing Platform renderer and dependencies with existing esbuild; extracts only scoped article/Mermaid styles, without importing the Platform global stylesheet or editing Platform.
- `tests/workflow/test_oem_capabilities_flow.py`: actual subprocess/socket HTTP acceptance and unlinked legacy projection regression.
- `tests/workflow/test_preview_manufacturing.py`: owned dataset startup, guards, business commands over socket, renderer DOM semantics, and failure preservation.

No new dependency, schema, domain command, frontend source, Platform source, source PPT, handbook, existing portfolio, employee session, browser/CUA, production database, release, or external messaging changes. The user's pre-existing modified handbook and untracked source PPT/dependency symlink remain outside this commit. Parent's already-reviewed documentation changes are unchanged.

## Actual integrated evidence

The same sample recipe is exercised through `BusinessHTTP`, which starts the existing private test host on a real 127.0.0.1 socket with separately authenticated synthetic roles. The preview itself never imports the private host or exposes its fixture routes.

Camera sample has an interrupted run with no quality verdict; a real failed measurement; nonconformance and qualified no-consumption fixture-adjustment rework route execution; a passing retest and separate rework completion; current NPI trial, issue resolution and approval. Original failed/interrupted history remains visible. Public asset publication uses a separately authored generic inspection check with explicit target-specific limits, while private customer details remain private. Robot sample has its own revision/route/material (joint drive control board), accepted trial, real passing run, required pinned public-asset adoption, and pending independent target verification/approval. Camera and robot calibrations remain pending in the prepared preview, with example `gain=1.25 ratio` requiring an independent source identity and matching simulated readback. Component removal/replacement and customer aliases retain the original factory SN and history. Both projects retain unstarted bulk units and actionable current work.

Socket acceptance verifies:

- Required target verification blocks approval, independent target pass permits approval, and later issue evidence invalidates current bulk eligibility despite historical approval.
- S5 shows the actual linked NPI blocker before approval and after invalidation; S2 stays unchanged. An unlinked NPI leaves all legacy progress stages identical.
- Target-only ordinary actor can read the sanitized catalog and own adoption, but source object reads return404. Public JSON contains no source project/issue IDs or private marker content.
- Exact operation replay returns the same issue without increasing issue count; changed-payload replay and stale CAS return409; revoked actor cannot replay or read the former project.
- A global admin session established before a future project's creation can execute its registered action without explicit project grant seeding.
- Calibration rejects reused calculation identity and mismatching readback; separate matching demo readback confirms. No quality/manufacturing release is silently created.
- Original SN/aliases/component history, aborted→failed→passing run history and final owned DB snapshot are checked. The private socket transport records request/response evidence beneath pytest's owned temporary directory.

## Preview ownership and host boundary

Preparation requires a new absolute path with no symlink ancestry and refuses any existing directory. It creates a0700 directory with a0600 owned manifest, distinct `demo` dataset UUID and synthetic admin UUID, an internal durable seed intent/receipt manifest, a fresh workflow/authority DB pair, copied business assets and a copied/hash-verified handbook. No arbitrary DB-path CLI option exists. Failure records remain in the incomplete owned directory; retry cannot overwrite/reset them. Create a different new directory to retry. Serving validates manifest purpose, exact directory, demo mode, completion, expected file inventory, regular ownership/no links or hardlinks, and all built asset hashes before constructing the router. Reopening does not reseed. The CLI holds an exclusive lock while serving.

Server binds only `127.0.0.1`, uses the actual bound port in an exact Host allowlist, disables trusted proxy headers, and requires exact Origin plus a per-process random CSRF token for every mutating request. Duplicate/missing header values cannot satisfy these checks. All responses have private/no-store, nosniff and DENY framing headers. No employee credentials, session cookies or remote identity are borrowed: the shell consistently identifies the local synthetic full-permission admin and simulated data. Swagger/OpenAPI and fixture/login/authority/reset/debug routes are absent. Asset serving is an exact four-file mapping; the business router additionally retains its existing strict two-asset endpoint. No filesystem directory server is mounted.

Exact renderer source:

`/Users/neo/Developer/work/AI-Agent-Platform/webui/src/manufacturingMarkdown.tsx`

Observed SHA256: `91a06e1b3c5acfc30bd8479bd856ca9d2557dc14739488a1ac45770548d2d4e1`.

The new manifest records the renderer source hash, stylesheet source hash, bundled dependency input hashes, and final business/bridge/CSS asset hashes. The bridge exports the original `createManufacturingMarkdownRenderer`; the shell passes its `renderMarkdown` directly to the actual `OrbbecManufacturing.mount`. Existing DOM tests execute this built bridge and verify real headings, GFM tables, code blocks, retired-handle safety and child-root cleanup. Only article/Mermaid selectors are copied and scoped to `.preview-shell`, with an explicit scoped mobile rule. No new Markdown parser is implemented. No browser screenshot or physical-device validation is claimed.

## RED/GREEN and fresh verification

Python: `/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python`. Commands below ran from the feature worktree; `<python>` denotes that executable.

1. New actual HTTP test before recipe implementation: `PYTHONPATH=src <python> -m pytest tests/workflow/test_oem_capabilities_flow.py -q` -> **1 failed**, missing new `workflow_demo.oem_preview` module.
2. Once the valid shared recipe executed through actual HTTP, the S5 regression failed specifically because S5 still said `1 actual records; completion requires current domain evidence` with no NPI blocker. Added exactly the `npi` kind to S5; full socket scenario -> **1 passed in2.03s**. During fixture development, an attempted consumptive rework exceeded the reserved initial material quantity; changed the actual registered fixture-adjustment route to explicit `material_consumption='none'`, with no invented inventory or domain relaxation.
3. New preview tests before host implementation: **1 failed,2 errors**, missing `preview_manufacturing`. After implementation and correcting bridge virtual-entry fingerprint handling: **3 passed in1.60s**.
4. Extended actual preview socket and exact renderer DOM coverage plus legacy projection: **7 passed in5.18s**.
5. Necessary current business build: `npm run build` in `webui` -> **exit0**, TypeScript and Vite,83 modules, `manufacturing.js`461.74kB and CSS34.05kB. No install or UI source edits.
6. Focused trio: `TEST_PLATFORM_SOURCE_ROOT=/Users/neo/Developer/work/AI-Agent-Platform PYTHONPATH=src <python> -m pytest tests/workflow/test_oem_capabilities_flow.py tests/workflow/test_preview_manufacturing.py tests/workflow/test_progress.py -q --tb=short` -> **17 passed in12.18s** before the two final isolation tests.
7. Affected backend regression: same prefix, tests `test_oem_capabilities_flow.py test_preview_manufacturing.py test_progress.py test_introduction.py test_laboratory.py test_admin_full_access.py test_action_capabilities.py` -> **66 passed in27.80s**. This preceded the scoped CSS extraction correction and the two extra preview isolation tests; domain code did not change afterward.
8. Self-review CSS regression RED: `... -m pytest tests/workflow/test_preview_manufacturing.py -k guarded_real -q --tb=short` -> **1 failed,4 deselected**, showing unscoped indented responsive selector incorrectly copied outside its media query. Restrict extraction to top-level renderer-owned rules, then add deliberate scoped responsive styles. Complete preview suite -> **5 passed in2.54s**.
9. Added allowed-database symlink/hardlink refusal and incomplete-preparation preservation. Fresh focused trio, exact command #6 -> **19 passed in9.81s**.
10. Strengthened duplicate replay assertion to check unchanged issue count; fresh `PYTHONPATH=src <python> -m pytest tests/workflow/test_oem_capabilities_flow.py -q` -> **2 passed in2.42s**.
11. Ruff format/check on the four new Python files -> **all checks passed**. `node --check scripts/build_preview_renderer.mjs` and task-scoped whitespace checks -> **exit0**.

All disposable HTTP servers were terminated and their stdout/stderr handles closed. Existing original36 registry and runners are unchanged. Parent owns the final whole-branch full workflow/original36 checks and final frontend evidence; no duplicated full regression was launched by this worker.

## Reproducible local preview commands

Run from the final reviewed checkout. Build once after final source integration:

```sh
cd /Users/neo/Developer/work/AI-Manufacturing-Platform/webui
npm run build
cd /Users/neo/Developer/work/AI-Manufacturing-Platform
PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python scripts/preview_manufacturing.py prepare --root /Users/neo/Developer/work/AI-Manufacturing-Platform/.superpowers/oem-preview-20261029 --platform-root /Users/neo/Developer/work/AI-Agent-Platform
PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python scripts/preview_manufacturing.py serve --root /Users/neo/Developer/work/AI-Manufacturing-Platform/.superpowers/oem-preview-20261029 --port 8765
```

The chosen preview root must not exist; pick a new name if it does. Its parent directory must already exist. Preparation invokes the renderer builder itself. Serving prints the exact loopback URL; with the command above it is `http://127.0.0.1:8765`. `localhost` is deliberately not an allowed Host. Port0 chooses an available loopback port and prints it. Stop with Ctrl-C; restart with the same serve command to retain local edits. There is no reset endpoint or automatic reseed. Parent performs the final launch; this worker has not left a preview server running.

## Self-review and limitations

Checked scoped routes and files, strict guard handling, source/domain command separation, simulated provenance, original six-project preservation, failure retention, absence of fixture endpoints, exact renderer input and styles, cleanup, CAS/replay/revocation, legacy progress preservation and tiny production diff. No blocking issue remains known. This preview is intentionally a synthetic local administrator, not a multi-user employee authentication system, production deployment, hardware/calibration execution, real customer approval, ERP integration, or factory acceptance. Both demonstration products use a limited explicit power/fixture check; it does not claim full robot or camera physical qualification. Failed/incomplete dataset recovery intentionally requires a new owned directory rather than automatic repair.
