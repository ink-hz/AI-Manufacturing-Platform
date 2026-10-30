# Opt-in workflow release and private candidate inputs

This runbook describes release tooling, not a deployment receipt. Build only from the final reviewed, merged MF `main` and PF `master` commits. Refresh the actual running container, image, full Compose chain, mounts, security, other containers, Nginx hash, source hashes and legacy data immediately before building/preparing and again before cutover. Do not infer these from Git tips. No Nginx change, reload, `-t -c`, or `-T -c` belongs to this release.

## Optional request configuration

The artifact baseline JSON may contain `baseline_workflow` and `target_workflow`, each with exactly these fields:

```json
{
  "database_path": "/app/data/manufacturing/workflow-demo.sqlite3",
  "authority_database_path": "/app/data/manufacturing/authority-demo.sqlite3",
  "dataset_id": "manufacturing-full-flow-demo-20261028-v1",
  "dataset_mode": "demo",
  "dataset_label": "全流程模拟环境"
}
```

Omit both for an unconfigured release. Omitting target while specifying baseline preserves that exact configuration. An explicitly supplied null, partial configuration, extra field, changed existing dataset/path/mode/label, alias of either database or `workbench.sqlite3`, symlink/hardlink, invalid path or mode is rejected. Paths must be direct `.sqlite3` files in the existing manufacturing data mount; the helper adds no persistent mount. Dataset IDs contain letters, digits, `_` and `-`, up to 96 characters. Labels must identify demo simulation (`demo`, `simulat`, or `模拟`); production labels must not imply a simulator. Production/test execution clocks and identity fixtures are not configuration fields. `test` is candidate-only; production configuration allows `demo` or `production`.

Only these five new environment keys are emitted: `PLATFORM_MANUFACTURING_WORKFLOW_DATABASE_PATH`, `PLATFORM_MANUFACTURING_AUTHORITY_DATABASE_PATH`, `PLATFORM_MANUFACTURING_DATASET_ID`, `PLATFORM_MANUFACTURING_DATASET_MODE`, and `PLATFORM_MANUFACTURING_DATASET_LABEL`. Baseline checks use only the pinned baseline configuration and prove all five keys absent when it is omitted. Unrelated environment, service, mount, network and security changes remain rejected.

Before cutover, online backups cover legacy, workflow and authority files that exist; missing initial files are recorded without creating them. Each backup is individually consistent; the three backups are **not** a cross-file atomic snapshot. Source rollback never restores those snapshots or removes database/WAL files, so post-cutover writes survive. Readiness initializes/validates schema and dataset metadata with no business rows or quality grants. Demo readiness verifies the independent mock authority store. Production readiness never constructs or opens the mock authority and explicitly reports `external_adapter_unverified`; this is not an external integration acceptance claim. Package initialization may import mock class definitions; that does not construct an adapter, open the authority store, or seed business data.

## Workflow schema advance and recovery

The rollback policy for a configured workflow is `forward_only_after_schema_advance`. For the OEM release, target readiness advances schema17 to21. Once committed, the previous schema17 release is **not a valid source-only rollback target**. Preserve the live database, WAL, audit history and post-cutover writes. Do not reset `schema_version`, delete sidecars, or restore a pre-cutover backup over live data. Repair forward with compatible code.

On cutover failure, the controller retains the persistent deployment/input locks before recovery and invalidates success markers. It records the original failure and recovery state before stopping anything. Only an exactly verified baseline or target API runtime is eligible for further action; unknown/missing/drifted runtimes fail closed. The controller rejects other running containers with overlapping writable data mounts. Before deployment, independently establish that no host importer or other process writes this dedicated database; Docker mount inventory cannot prove absence of arbitrary host writers. The release locks serialize cooperating deployment tools. Stopping the full API container stops its request workers and threadpool together.

The exact verified container ID is stopped and confirmed stopped before the authoritative probe. A separate one-shot container uses the pinned target image, UID10001, network none, read-only root, cap-drop ALL and no-new-privileges. The pinned previous MF source and existing manufacturing data remain read-only bind mounts. A private UID10001-owned 0700 `/tmp` tmpfs is limited to 32MiB with noexec/nosuid/nodev. The helper receives only approved workflow configuration and fixed paths, not API runtime secrets; it parses the previous source's literal `SCHEMA_VERSION` without importing business code.

After the existing writer exclusion and stop checks, the probe always copies the workflow main DB and its adjacent WAL (if present) into a fresh private directory; combined source size is limited to 16MiB before allocation and during streaming. Source descriptors are read-only/no-follow. Before and after copying, and again after querying, it verifies source paths/open descriptors, device/inode, size, mtime/ctime, sidecar presence and DB/WAL SHA256. SHM is never copied; SQLite can rebuild it only in tmpfs. Any rollback journal, source change, oversized input or copy/query error refuses rollback. A zero-byte WAL is accepted as a no-frame state; malformed nonempty WAL headers, frames, salts or checksums are refused, including benign stale trailing frames that SQLite might otherwise ignore. This conservative refusal may require forward repair.

SQLite opens only the verified private copy with `mode=ro` and `query_only`; it never opens the production DB through SQLite, uses `immutable=1`, changes source metadata or calls WorkflowStore. Version/dataset/integrity and path/alias checks remain required. Results identify the original configured database path, snapshot method, source sizes/hashes and verified stability. SQLite/overall execution deadlines bound the probe. Copy stability checks do not establish absence of an idle writer or replace mandatory quiescence; a read-only diagnostic while the API runs is not rollback authorization.

Only an exact same-version result with verified dataset identity permits old Compose recreation. Target remains stopped through the compatibility check and recreation. Runtime, content, Compose and other-container checks still apply; the restored old code must also complete `READINESS_CODE` with the exact schema/path/dataset. Only then can `rollback.json` say `restored:true`. Locks are released only after that receipt is published.

Incompatibility or uncertainty never invokes old Compose. If this handler stopped the verified runtime before recreation began, it attempts to start that **same container ID**, verifies its runtime and generic health, and records the result. Generic health of a restarted target does not assert workflow readiness or repair the original cutover failure. A failed stop command is inspected because it may already have stopped the container. After an attempted old recreation, failure requires operator inspection; the controller does not restart a stale target ID or guess which runtime survived. Receipt-write and readiness failures retain locks. An initially unconfigured workflow has no proven baseline workflow schema and therefore cannot pass the configured-workflow compatibility gate; releases with no workflow configuration retain their legacy rollback behavior.

Inspect `cutover-failure.private.json`, `workflow-rollback-state.private.json`, operation receipts, `rollback.json` (if present), and `locks-retained.private.json` alongside actual runtime/schema before reconciling locks. The recovery state records stop/probe/recreate phases, compatibility evidence, original failure, restart outcome, `old_runtime_restored` and `forward_repair_required`; an intermediate phase after interruption is not recovery success. Successful `future-maintenance.json` records baseline/target schema versions, actual workflow readiness and this forward-only policy. None of these receipts authorizes database downgrade or automatic backup restoration.

## Exact source overlay

The reviewed baseline has seven modified PF files: `control_plane/auth.py`, `control_plane/authorization.py`, `control_plane/middleware.py`, `control_plane/routes_auth.py`, `main.py`, `manufacturing.py`, and `manufacturing_paths.py`; `manufacturing_security.py` is added. List all eight relative to `backend/app` in `approved_backend_files`, and only the new file in `approved_backend_additions`. Recompute this from the final reviewed refs and actual image; do not copy an entire backend directory.

The request maps `backend_base_hashes` and `backend_hashes` have identical keys. A reviewed creation has a null old hash and appears in `backend_added_files`; only actual image absence satisfies that pin. Every other file has exact old/new SHA256 hashes. Deletions, renames, executable/symlink Git entries, unreviewed additions and unsafe paths fail before export. Installer and prepare validate the actual baseline map before the COPY overlay; candidate validates the entire resulting source/static maps. The actual repository root is `/app`, with Python source at `/app/backend/app`, not `/app/app`. Unrelated image patches remain part of the runtime map, without pretending the whole image equals the PF commit.

## Prepare private runtime assets outside production

`deploy/candidate_fixture.py` exports and validates private test assets. It does not download dependencies, run an installer, create mounts, or invoke Docker. Prepare a Linux x86-64 glibc-compatible Node binary and the **exact final MF `webui/package-lock.json`** dev/test dependencies in a disposable preparation environment. Use `npm ci` against that unchanged lock there; never install into the API image, production package, or production host environment. Node must satisfy the installed Vitest engine (22.12+, 24.x, or >=26). Host Node18 and the cached musl Alpine Node are not candidate portability evidence. Node26.5.0 Linux-x64 is an available preparation choice; verify its archive against the official versioned SHASUMS independently. Actual execution inside the candidate remains mandatory.

The prepared runtime directory contains `bin/node`, `node_modules/vitest/vitest.mjs`, and every locked Linux dependency/native asset. Resolve internal dependency symlinks during private preparation, rejecting any target outside that preparation tree; the final input must contain only regular files/directories. Include required runtime libraries in the pinned tree if the image does not supply compatible libraries; use a compatible directly executable Node binary, not a wrapper that changes the E30 executable identity. This helper supplies no `LD_LIBRARY_PATH` or arbitrary command override; unresolved binary compatibility is a failed candidate prerequisite.

Create the runtime manifest outside its own tree using the reviewed helper:

```python
manifest = {
    "version": 1,
    "platform": "linux-x64-glibc",
    "node_version": "v26.5.0",  # actual prepared executable version
    "lock_sha256": candidate_fixture.digest(final_mf_lock),
    "files": candidate_fixture.file_hashes(prepared_runtime),
}
```

Serialize JSON, then retain its externally computed SHA256. The helper checks that pin, complete runtime/dependency file inventory, lock hash and engine contract. It rechecks the actual Node version inside the candidate. This is not a claim that a manifest string alone proves binary compatibility.

## Export and pin source inputs

After the final artifact build, invoke this local Python interface from `deploy` on the reviewed MF source, using actual immutable business output and the fresh whole image source map:

```python
pin = candidate_fixture.export_fixture(
    repo=mf_repository, sha=final_mf_sha, platform_sha=final_pf_sha,
    business=payload_business_directory,
    preflight={
        "old": {"Image": actual_baseline_image_id},
        "expected_source": {**actual_baseline_source_hashes, **request["backend_hashes"]},
    },
    runtime=prepared_runtime, runtime_manifest=runtime_manifest_path,
    runtime_pin=external_runtime_manifest_sha256,
    output=new_private_fixture_directory,
)
```

The export is from Git commits, not worktree edits. It includes current private test/scenario/React/config sources, compiled current MF assets, and separately pinned genuine A1 `b7397b4c0acd2bb9d32cafade8e885e4b9e7c732` and legacy `ec41b39bdf8c0b5cc6b0193ed646a44050106ca3` source exports. No `.git`, pytest installation, identity helper, Node dependency, or test fixture enters the production business export. The private fixture also contains `controller.py`, exported from the exact MF commit’s `deploy/candidate_fixture.py` and normalized to0444. Its hash is included in the externally pinned fixture map and must equal the installed root-only controller tool. Candidate loads this validated copy at `/candidate-fixture/controller.py`; the installed top-level tool stays0600 and the parent stage stays0700. Old compiled assets are not claimed; current assets are only loader prerequisites for old API compatibility.

Put the fixture at exact private stage child `candidate-fixture`, runtime at `candidate-runtime`; add the returned `candidate_fixture_sha256` to the root-owned `request.json` **before prepare**. The fixture can be exported before prepare using the fresh independently captured map above; prepare itself verifies that actual map again. Runtime and fixture roots are root-owned, directories readable/searchable and files readable by UID10001, without group/other write bits (typically directories0555, files0444, executable Node/native files0555). Their parent release stage remains root0700. All fixture/runtime inputs are mounted read-only.

The source envelope is externally pinned, validates current test sources, MF runtime export and all applicable PF runtime files. OCI identity, actual baseline and approved overlay are checked by the controller outside the candidate; file checks inside the image cannot substitute for that outer check. `WORKFLOW_*` paths/hashes/commands and synthetic clocks/identities stay private and never enter Compose or the image.

## Bounded writable candidate evidence

Provision **only a new, explicitly owned** dedicated filesystem at `<stage>/candidate-evidence`; the helper never formats, mounts or unmounts it. Use a 512MiB disk-backed filesystem with at least65,536 inodes (for example an explicitly owned sparse ext4 image created with `mkfs.ext4 -N 65536`, then mounted by the release controller). Do not run generic format/mount commands against a discovered or reused device. Record its backing-file identity, mountpoint, mount options and ownership before use. Remove filesystem-created `lost+found` only after proving this is the new owned filesystem and it is empty; the candidate evidence root must start empty.

The exact mountpoint must be a different device from the stage, owned10001:10001 mode0700, capacity between448 and512MiB, free space at least448MiB, total inodes at least65,536 and free inodes at least50,000. The parent stage needs at least520MiB and16 free inodes for the outside archive/receipt. The measurements motivating these bounds are approximately231MB/23,465 files for accepted36 and393MB/35,942 files for all retained local attempts. These are local allocation measurements, not Linux proof: record actual Linux bytes/inodes and Node/cache scratch on the first candidate. If capacity is insufficient, preserve that failure and review the measured cause; do not truncate proofs or silently expand limits.

Candidate has network none, read-only root, UID10001, cap-drop ALL and no-new-privileges. `/tmp` remains32MiB. Only this private filesystem is mounted writable; no production data/secrets mounts are used. Its own generated config preserves the original test settings and redirects Vite cacheDir to `/candidate-evidence/vite-cache` and Vitest 5's separate `test.fsModuleCachePath` to `/candidate-evidence/vitest-module-cache`; source and dependency mounts remain read-only, and explicit JSON reporter outputs also belong under evidence. The module cache is not disabled and shares the existing bounded evidence filesystem; home, cache, test outputs and scenario databases also stay private. The existing isolated `/tmp` legacy/workflow/authority smoke paths are distinct. The complete CLI invokes the same registry with `--cases all`, mandatory actual E30 React and E29/E31/E32 D3 proofs, using pinned Node and JSON argv. There is no skip or static fallback.

The controller removes the explicitly named private candidate container before archiving, including after CLI failure/timeout, so no child process can mutate evidence during hashing. `candidate-evidence.tar.gz` and `candidate-evidence-receipt.json` are written outside the bounded filesystem; receipt includes SHA256, every evidence file hash, the evidence root’s device/inode identity and actual logical/allocated usage/free-byte/inode readings. Existing operation logs also preserve candidate stdout/stderr. A container-removal or archive failure leaves evidence in place and blocks success. No automatic retry or deletion occurs.

Only after independently retaining/verifying the archive, explicit cleanup is available:

```python
candidate_fixture.cleanup_evidence(stage, receipt_sha256)
```

It checks the exact mount/owner/capacity and recorded device/inode identity, pinned receipt, archive hash and unchanged complete evidence file map (including a legitimate empty map after a pre-write failure), removes only those verified contents, and leaves the filesystem/mount in place. Retain first failures and archives across any selected rerun; use a new release stage/receipt for a new candidate attempt. User browser acceptance and real external-service acceptance remain separate from this synthetic candidate gate.
