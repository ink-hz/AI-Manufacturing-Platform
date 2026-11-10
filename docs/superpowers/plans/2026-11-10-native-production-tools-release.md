# Native production tools release plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for the scoped release-tool change, then execute the operator stages sequentially.

**Goal:** Publish the reviewed native 产测管理 module and fixed native dependencies to the existing manufacturing host without changing business data or unrelated applications.

**Architecture:** Derive from the actual healthy API image, preserving every image default and existing dependency. Add one explicitly versioned COPY-only SDK payload containing only six missing distributions, overlay the two reviewed PF manufacturing files and immutable MF business export. Existing release locks, Compose parity, backups, candidate36, recovery, source/static and unrelated-container guards remain mandatory. Real project bindings stay disabled until the user supplies an approved production mapping; local verification UUID mappings are never promoted.

**Tech Stack:** Existing Python release helpers, Docker/Compose, pinned Linux CPython3.11 SDK tree, existing Node24.7 Linux candidate runtime and immutable source fixtures.

## Global Constraints

- User authorized production release on2026-11-10. No repeated deployment approval gate.
- Read PF AGENTS.md. No Nginx command/config/reload; no other-service recreation; no source DB/OSS mutation; no schema24 change/downgrade or live DB restore.
- Actual baseline API44ae429f7fd57d44a8eb17facb7b0bf7c7c8ed9bd21cc2aea595e98569abe401, image58682c35a3bc630e715fa480b688121cd68d01afa40f150bcaeef7e20e1166f6, PF3c844cbb, MF455fe487; refresh all facts before prepare/cutover.61 ordered Compose inputs,35containers, existing demo dataset unchanged.
- Current release tool accepts only COPY backend/static. Add an opt-in versioned native-SDK profile; preserve the exact old Dockerfile and guards for absent profile. No generic RUN/pip/extra-COPY allowance.
- Native SDK tree is built in disposable Linux preparation, never installed into live API/container/host/shared venv. Candidate build network none and copy only; no dependency downloads during build/candidate/cutover.
- Exact missing distribution pins: PyMySQL1.2.4, oss2 2.19.1, crcmod1.7, pycryptodome4.4.0, aliyun-python-sdk-kms2.16.5, aliyun-python-sdk-core2.16.1. Existing requests2.34.2/six1.17.0/jmespath1.1.0/cryptography50.0.0/psycopg3.3.4 preserved.
- Profile native-production-tools-sdk-v1 additionally pins the root-approved 622-file, byte-exact manifest SHA-256 e4e998c94b019b1d636fafead91e349b9bdbd00d6acff53be5dbf12856505517 in code. The root operator retains trusted wheel provenance, exact tree and content-review evidence privately; arbitrary credential files are excluded without banning legitimate upstream credentials.py code. Any changed tree or manifest serialization requires a newly reviewed profile; a caller-updated request pin cannot authorize it. Synthetic local tests may explicitly inject a synthetic approved pin, never production evidence.
- Runtime comparison remains inspect-only, including stopped-target rollback verification. Execute SDK imports/content/version checks only in live candidate/post-cutover readiness gates.
- The SDK profile manifest is hash-pinned, files-only inventory, Linuxx86_64/CPython3.11, exact known distribution set; forbid symlinks/traversal/unknown top-level packages, overwritten baseline site-package files, pycache and credentials. Check files/versions inside candidate and deployed target.
- If native settings are enabled, only the two explicit existing host variable names may be added; both paths inside a new private native-production-tools directory in the existing manufacturing data mount. No new mount. Missing business mapping remains closed; no name matching or synthetic business project creation.

### Task 1: Strict native dependency/config release profile

Files: add deploy/native_release.py and deploy/tests/test_native_release.py; minimally extend deploy/install_payload.py, release.py, release_guard.py, candidate_verify.py, build_artifact.py TOOLS and install_payload TOP where needed; update runbook. Existing default behavior unchanged.

- [ ] Write failing tests for explicit profile shape/pins/hash/tree/path/nonoverwrite checks, exact extra COPY Dockerfile, candidate version/content checks, and optional two-path native environment preservation. Default no-profile test must assert existing exact Dockerfile/Compose rules still reject unapproved operations.
- [ ] Implement native_sdk request field with exact profile native-production-tools-sdk-v1, Python3.11/Linuxx86_64, files map and exact six distributions. Native tree location build/native-sdk; Dockerfile adds exactly COPY --chown=0:0 native-sdk/ /usr/local/lib/python3.11/site-packages/ before existing two COPYs. No USER/RUN/ENV alteration. Validate baseline absence before build, resulting content/versions in candidate, manifest hash under snapshot_files.
- [ ] Optional baseline_native/target_native objects contain exactly config_path and snapshot_path; paths fixed beneath /app/data/manufacturing/native-production-tools/. Both absent preserves current behavior. Existing baseline native values must remain exact if present. Validate secret regular/nosymlink/private ownership and snapshot isolation using dedicated file checks. No wildcard env allowance.
- [ ] Run all deploy/tests, scoped lint/diff checks, independent task review; fix findings; commit then merge/push main before artifact export.

### Operator stages (root only)

- [ ] Retain fresh actual runtime/maps/Compose/input hashes/Nginx/all containers/three-database logical baseline and latest maintenance pointer privately; verify only two PF backend files differ from actual pinned baseline.
- [ ] Build exact six SDK distributions in disposable Linux preparation against actual base; preserve logs/wheel hashes, manifest and baseline collision check. Do not upgrade existing packages.
- [ ] Export MF and reviewed PF two-file overlay from accepted main/master SHA. Preserve current platform static asset map. Export current fixture and exact existing Linux Node runtime; create new owner-private release stage and bounded512MiB candidate evidence filesystem using existing guards.
- [ ] Install/build, prepare exact61-input replay, run mandatory36-case isolated candidate and extra native module/SDK/socket regressions in actual image, with no production data/secrets/network. Independently verify complete artifacts, JUnit and hashes; retain any first failure and use new stages for corrected attempts.
- [ ] Resolve user mapping response. Without explicit approved mapping publish code/SDK with source configuration disabled and clearly report this limitation. Do not invent mappings or attach real records to demo projects.
- [ ] Refresh runtime/writer exclusion/all-container/input/Nginx baselines; online backup all existing manufacturing DBs; controlled API-only cutover with source-only same-schema rollback support. No schema migration expected.
- [ ] Verify healthy/restarts/image/source/static/resource hashes, all other containers/input chain unchanged, sixproject45SN logical preservation, anonymous401/no-store and read-only native status under existing real grants. Actual source reads only if approved bindings exist. Keep browser acceptance user-owned.
- [ ] Write tracked release receipt with exact commits/image/time, enabled vs unconfigured source state, checks/failures/skips and recovery pointers. Commit/push docs; leave user materials untouched.
