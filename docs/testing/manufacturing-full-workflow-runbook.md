# Isolated manufacturing workflow acceptance

This runbook describes the reproducible harness for the original [36 business cases](manufacturing-full-workflow-acceptance.md). It is not a full acceptance report. D2 authored the exact registry and verified a complete F01 smoke and E30 component/HTTP case; D4 must run a fresh `--cases all` with the D3 proof runner configured. Browser, employee-account, real external-system and production acceptance remain separate.

## Run a selected scope

Run from the manufacturing source checkout with its runtime dependencies, an installed Python executable, and an absolute private output directory:

```sh
PYTHONPATH=src /path/to/python scripts/run_workflow_acceptance.py \
  --cases F01,F02 --seed 41 --output /absolute/private/workflow-evidence \
  --business-clock 2026-10-28T00:00:00Z
```

`--cases all`, `F01,F02`, and `E10,E26` use the identical pytest-independent `ScenarioRegistry`. Unknown/duplicate IDs, non-UTC clocks and relative output paths fail before creating case state. Exit 0 means every selected case passed; exit 1 means at least one selected case failed/blocked; malformed arguments exit 2. Each run gets a new unpredictable run ID and every case owns separate workflow/authority databases. `run.json` lists all 36 statuses; unselected IDs are `not_executed`. No earlier subset result is promoted into an all-case pass.

The script uses the current Python executable for a loopback Uvicorn child process. It needs the host runtime's FastAPI/Pydantic/Uvicorn dependencies, not pytest. `TEST_PLATFORM_SOURCE_ROOT` selects the exact sibling platform source checkout for provenance; the workspace sibling is the default. Source manifests include both Git commits and worktree status, content hashes of relevant tracked/untracked candidate source, a source release hash, runtime Python/SQLite/package versions, seed recipe, fixed business clock, dataset identity/mode, synthetic identity boundary and authority fault boundary. The dependency symlink is recorded separately. These manifests describe the source actually tested; committing later never rewrites an earlier run.

The fixed business clock drives simulated source eligibility, material expiry, readiness, command facts and authority receipts. Login/security/audit wall time, process startup deadlines, evidence timestamps and elapsed monotonic durations remain real. Source timestamps, planned use, calibration and expiry derive from the scenario clock. No time nudges or timestamp/UUID tie breaking establish acceptance order.

## Evidence and failure handling

Every HTTP request/response has an append-only numbered artifact; each response links its request artifact. Credential fields are redacted. Synthetic fixture secrets are mode-0600 startup inputs removed after login and recreated only for a fresh process. Platform mutations use cookie sessions, Origin/CSRF and live roles/qualifications. Test users and fixture routes exist only in `tests/workflow`, outside the production package. External receiving/IQC/customer approval/fault injection and delivery of already-persisted outbound requests occur only at the explicit mock authority boundary. No helper inserts platform success facts with SQL.

Read-only SQLite snapshots preserve the actual final workflow and authority facts, including failures and foreign links. They supplement API/detail/dashboard/trace assertions. The harness takes one final snapshot of each database, not a binary copy per request. `result.json` retains the first unexpected error and all artifact paths; a teardown error cannot erase an earlier business failure. A second attempt to run the same context fails before any action. Expected 400/403/409/422 and unknown-receipt outcomes are explicit assertions, not retries hiding failures.

For a selected failure, use a new run linked to its previous case directory:

```sh
PYTHONPATH=src /path/to/python scripts/run_workflow_acceptance.py \
  --cases E21 --seed 41 --output /absolute/private/workflow-evidence \
  --resume /absolute/private/workflow-evidence/old-run/E21
```

There is no reset endpoint. The default always creates a new directory. Optional CLI deletion requires both an exact harness-owned manifest and an explicit matching `--dataset-mode test` or `demo`:

```sh
/path/to/python scripts/run_workflow_acceptance.py \
  --delete-owned-run /absolute/private/workflow-evidence/disposable-run/E32 \
  --dataset-mode test
```

Preserve failed acceptance evidence. This deletion facility is for explicitly disposable owned test/demo data and refuses unowned/production manifests and direct symlinks; it is not a mechanism for production cleanup.

## Original numerical flows and source boundaries

F01 executes Camera100 with physical work orders60+40, genuine trial/first article/bulk execution, measured tests, independent releases, shipments/signatures/acceptances60+40, the remaining40 check, feedback/CAPA and independent fulfillment/cost/quality closures. Every SN has a reverse trace assertion and persisted quantities are checked.

F02 retains the original physical trial work order5 at M1. A separately planned M1 work order15 is actually switched through the authority to a new M2 work order15 after the five-unit trial defect/repair. The old planned15 snapshot remains, with effective obligation0; current effective scope is5+15, allocation20. Old trial execution/tests remain unchanged. E04/E11 separately cover a partially executed immutable WO20 with effective old5/new15.

F03 keeps Printer10/work orders6+4 and explicit printer route/limits, rejecting camera test evidence. F04 keeps OEM30/C1/M1, separate customer and manufacturer material owners, actual consumption of both lots, required customer release,10+20 deliveries and customer material consumption/return reconciliation. E05/E06 use100 material pieces,80 initially qualified,20 arriving with15 accepted/5 rejected, then5 replacement; they do not convert in-transit promises into readiness.

Cost closure is a real `closure.record` command manually recording a signed **synthetic external ERP cost-close receipt**. The owned external fixture artifact retains a stable receipt ID, project, source, business time and signatory; its SHA256 is admitted as source evidence and the accepted source and closure are asserted. It does not claim an ERP API integration, add accounting vouchers, or reuse another closure's decision. WMS/IQC/MES reservation/start/shipment/containment receipts are separately produced by the stateful mock authority.

## Required E30 private React bridge

E30 includes actual ReactDOM rendering of `App`, two synthetic server sessions, an actual HTTP CAS conflict, retained form data, the full handbook response/digest and end-of-document rendering, restored workspace context, and exactly one departure after abandonment with no second dialog. JSON UI evidence and Vitest results remain separate from API/SQLite evidence; both are required. These are component interactions, not browser automation or user visual acceptance.

The default local command uses Node and the checkout's Vitest entrypoint with `--configLoader runner`; `WORKFLOW_E30_COMMAND` can supply a JSON command prefix for a reviewed private runtime, for example:

```sh
export WORKFLOW_E30_COMMAND='["/private/test-runtime/node","/private/test-assets/node_modules/vitest/vitest.mjs"]'
```

The manifest records the command, Node binary digest/version and package-lock digest. E30 fails/blocks if this required runtime or evidence is unavailable; API-only or static source checks never replace it. The actual candidate image currently has no Node/npm. R1 must supply a separately pinned Linux Node executable and exact-lock Linux test dependencies/native modules on private read-only mounts, executed **inside the isolated network-none candidate** using its loopback host. The Mac `node_modules` symlink is not a Linux runtime. No dependency is installed into the production package/image and no candidate network is attached.

## Mandatory D3 proof handoff in the same registry

E29, E31 and E32 first perform their local real-HTTP actions, then require `WORKFLOW_D3_PROOF_COMMAND`, a JSON array naming a reviewed absolute private runner. Its absence makes the aggregate case **blocked**. It is not a passed subset. The pytest-independent runner is `tests/workflow/d3/run_proof.py`; configure it for D4's all36 run. It extends these exact registered cases and does not substitute a second acceptance suite.

The harness invokes the command with `--case ID --case-directory <owned-dir> --output <owned-dir>/d3-proof.json`. It records the exact command and hashes of regular absolute runner files. The runner must return case_id, dataset_id, seed, release_hash and runner_files matching this run, plus `assertions` keyed by every required assertion below. Each assertion must have `passed: true` and a nonempty `evidence` list of `{path: "case-relative-path", sha256: "..."}` referencing actual owned request/response/restart/DB evidence. Missing files, foreign paths, symlinks and mismatched digests/provenance are rejected. A status checklist without evidence cannot pass. R1 additionally reviews/pins the actual private runner/dependencies rather than trusting arbitrary self-declared proof.

| Case | Required D3 assertions |
| --- | --- |
| E29 | `pf-real-identity-csrf`, `project-customer-action-acl`, `qualification-revocation`, `retired-page-callbacks`, `legacy-endpoints-protected` |
| E31 | `actual-host-fresh-process-sessions`, `all-critical-phase-readback`, `api-db-dashboard-consistency`, `idempotent-resume`, `historical-create-replay-compatibility` |
| E32 | `seven-legacy-created-by-real-api`, `all-legacy-table-hashes-unchanged`, `owned-demo-reset-only`, `seeded-mock-state-replay`, `persistent-simulation-labels` |

E31 locally restarts through reviewed order, reserved readiness, measured/released production, shipment, accepted feedback and independent closures, comparing logical SQL facts and API state with fresh sessions. D3 adds the actual host/migration matrix, including the actual A1-source project-create replay (not SQL-fabricated historical success), live authorization on replay and immutable operation history. E32 runs two alternate-seed registered E14 scenarios and changes mock fault state through the boundary; the seven-record legacy/reset proof remains mandatory. Those seven synthetic legacy records must be created through actual legacy APIs; they are not the production seven. Root's production baseline/cutover checks remain separate.

## Actual PF process and historical compatibility proof

Configure the private runner with the same Python runtime used by PF. Paths below are examples and must resolve to the reviewed private exports:

```sh
export WORKFLOW_D3_PROOF_COMMAND='["/private/python/bin/python","/private/manufacturing/tests/workflow/d3/run_proof.py"]'
PYTHONPATH=src /private/python/bin/python scripts/run_workflow_acceptance.py \
  --cases E29,E31,E32 --seed 73 --output /private/evidence/d3
```

E29 and E32 also use the exact-lock Node/Vitest runtime configured by `WORKFLOW_E30_COMMAND`. They execute the real MF API retirement/order component tests and persistent simulation-label tests. Owned Vitest JSON must contain the exact required assertions with `passed` status; skipped/todo tests and source text searches cannot satisfy proof. PF frontend dependencies are not required.

`d3/pf_host.py` starts actual PF `create_app` with its identity middleware, route policy registry and real `AuthorizationService`. Only the external identity provider and its read-only synthetic grant repository are fixtures. Sessions use the real login endpoint and fresh real-UTC security timestamps; HTTPS uses an ephemeral loopback SAN certificate verified by the client. Certificate generation uses the existing `cryptography` runtime, without new production dependencies or CLI tools. Synthetic principals, private fixture configuration and the temporary login secret are confined to an owned test dataset. No employee session, caller role header, HTTP flag or production environment setting enables this fixture.

PF's optional trusted constructor dependencies `identity_authorization` and `manufacturing_business_clock` retain the default production behavior when omitted. The business clock is forwarded only to a factory explicitly declaring `business_clock`; an older factory remains compatible with the default path, and a requested clock on an unsupported factory makes the workflow unavailable. Security/JWT/provider/certificate/artifact time remains actual UTC. Fresh child processes reuse only the owned databases, then obtain new sessions. An old session must fail after restart. The parent checks scoped dashboard counts against SQL, immutable domain/API state, and authority database hashes before and after each critical checkpoint. Owned proof process groups have a 60-second deadline and bounded termination/kill cleanup; unrelated processes are outside that group.

The parent rehashes the transitive owned JSON evidence and actual proof helper/scenario files. It independently rehashes every recorded executed PF module and the private MF release files, and reopens the final domain, authority and legacy databases to check every recorded table count/hash. The actual E31 proof produces100 units, restarts after first article and after shipment60 before acceptance, then accepts all100; the separate reservation checkpoint confirms80 with one authority business operation despite concurrent retries. E32 creates seven real legacy API projects with task/package controls, runs a released/shipped/accepted workflow, and proves every legacy table unchanged through an independently owned test-dataset reset.

Two historical exports are required in a Git-less candidate:

| Prefix | Exact source commit | Purpose |
| --- | --- | --- |
| `WORKFLOW_A1_SOURCE` | `b7397b4c0acd2bb9d32cafade8e885e4b9e7c732` | Original A1 router creates schema1 project and original replay bytes |
| `WORKFLOW_LEGACY_SOURCE` | `ec41b39bdf8c0b5cc6b0193ed646a44050106ca3` | Genuine pre-workflow source bootstrap compatibility |

For each prefix supply `_ROOT`, `_MANIFEST` and `_MANIFEST_SHA256`. Each separately externally pinned manifest has exactly `{version: 1, commit: "...", files: {"src/...": "sha256..."}}`. It covers the entire original `src` export. The runner validates the expected commit, manifest hash, safe paths, all file hashes and exact source inventory, refusing extra injected source files. Without main candidate provenance, local development may export these exact commits with `git ls-tree`/`git show`; candidate execution does not require Git history. R1 prepares and pins both private read-only assets outside the candidate. The legacy export has no matching historical compiled UI artifact: its case proves old-source/API bootstrap, using separately verified current assets only as loader prerequisites. It makes no historical asset compatibility claim. Actual current-source shell/assets/handbook bytes and CSP are positively checked.

Schema16 canonicalizes only indexed source identity columns across demands/order lines/work orders, using the same system/type case-folding and external-ID case-preserving helper as current writers, lookups and amendments. All three domains preflight their existing uniqueness scopes before any update. A collision aborts the whole migration; raw source JSON, operations and audits remain immutable.

A1 creation replay uses an explicit untagged v1 adapter with an exact old field set, original action/version, original request hash and audit/object binding. Both original and normalized stored quantity must satisfy the same positive, finite, exact-scale quantity validation. Only creation-time empty stages and zero child quantities are derived; a later real order100 remains visible in current reads while the original creation replay stays zero. Current DTOs stay strict. Live original-project authorization precedes caller hash comparison, including changed payloads and cross-action UUID conflicts; active changed payloads return409 and revoked scope returns404. Historical A2/A3/B3 source projections bind original typed command, operation hash, object and physical source facts without consulting a writer's current qualification. Unverified source references are omitted from public evidence while private audit bytes are retained.

## Verification scope and capacity

The focused default command runs harness/clock/restart contracts and a full F01 smoke:

```sh
PYTHONPATH=src /path/to/python -m pytest tests/workflow/test_acceptance.py \
  tests/workflow/test_dataset_isolation.py tests/workflow/test_business_clock.py \
  tests/workflow/test_restart.py -q
```

There are real `test_f01`–`test_f04` and `test_e01`–`test_e32` wrappers. F01 is the required default smoke; the other35 wrappers are explicitly unselected unless `WORKFLOW_ACCEPTANCE_CASES=all` or a comma-separated selection is set. Their pytest skips are **not business passes**. D4's fresh all36 CLI execution is mandatory; record exact selection if a later unit regression excludes already-executed heavy wrappers to avoid duplication.

The initial complete working-tree F01 took5,320ms and used10,839,186 bytes/2,772 files (workflow.db2,285,568; authority.db331,776; final workflow snapshot1,363,079; authority snapshot172,874). This is one case, not an all36 capacity estimate. R1 must measure complete evidence plus private runtime needs against the actual candidate budget; do not truncate evidence or silently enlarge `/tmp` to claim a pass.

## Git-less candidate provenance

Normal execution resolves the actual approved PF worktree (`AI-Agent-Platform/.worktrees/full-workflow`), not canonical master. A private candidate can instead set `WORKFLOW_SOURCE_MANIFEST` and the externally pinned `WORKFLOW_SOURCE_MANIFEST_SHA256`. The envelope is strict version1 with `source` (the normal live-Git export), `manufacturing_runtime: {files: {...}}`, and `platform_runtime: {target_commit, baseline_image, approved_overlay, files}`. File maps are nonempty, bounded, relative-path→SHA256 mappings. `baseline_image` is the externally approved OCI `sha256:...`; `approved_overlay` identifies the reviewed commit or overlay digest. The target PF commit must equal the export's platform commit.

R1 prepares and pins this envelope outside the candidate from exact reviewed worktrees and the actual image/overlay. It mounts the complete private MF test tree plus the actual production MF export, and supplies `WORKFLOW_MANUFACTURING_RUNTIME_ROOT` and `WORKFLOW_PLATFORM_RUNTIME_ROOT`. Before creating case state, the validator checks the external envelope hash, schema, safe nonsymlink paths, every private MF input hash, the separate build-asset hashes, every exported business/handbook/build file against the actual MF runtime export, and applicable PF manufacturing/identity-middleware files against actual runtime paths. The child HTTP host imports the validated runtime export's `src` and disables bytecode writes. Missing/mismatched inputs fail preflight.

Inside the candidate, provenance is labelled `pinned_export` and retains the **original export** tree state; it does not claim live Git inspection or a clean checkout. Applicable PF runtime file hashes are checked independently because the actual image preserves baseline patches and overlays reviewed deltas; it is not assumed identical to an entire host checkout. R1 separately proves actual OCI image identity and approved baseline/overlay outside the candidate. D3 binds the concrete PF files its proof runner executes. No caller HTTP field can override any of this configuration.

## Complete-chain proof and failure diagnostics

Every SN in F01–F04 now compares exact typed graph node IDs and edge tuples with independently read persisted identities, refusing truncation. The composite proof reconciles execution source/admission/start receipt and fixed route, actual consumed material ownership, first tests/retests/rework, independent releases, authoritative shipment receipts and signed/accepted quantities. Each main flow supplies one actual completed RMA/CAPA pair and proves its exact delivered-unit/test linkage;100 RMAs are not required. The graph is not expected to expose execution/acceptance facts that belong to typed APIs/SQL.

E12 uses business-now < equipment-expiry < future-planned-start, while every other required check passes. It asserts equipment is the only blocker and production.start is refused, appends only renewed equipment evidence, re-evaluates, and successfully repeats the same action. Failure artifacts include file/line/function frame metadata without source lines or local variables; original first-error and teardown semantics are preserved.
