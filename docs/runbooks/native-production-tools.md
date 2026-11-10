# Native production tools v2

产测管理 independently reads source observations. Every HTTP request requires the
host's current `Actor.configuration_admin=true`; read-only administrators can read.
Ordinary manufacturing members receive 403 before source I/O and anonymous requests
receive host-owned 401. A manufacturing project, dataset binding or project grant is
not required. The separate 测试与标定 workflow retains its controlled business role.
No observation automatically creates tests, quality releases, inventory or work orders.

## Host and private configuration

The package exports `NATIVE_PRODUCTION_PROTOCOL=2`,
`build_native_config(config_path, snapshot_path)`, `validate_snapshot_path` and the
optional `production_tools` workflow-router keyword. The host must verify protocol 2
before calling the two-argument factory. Exactly nine GET routes are protected under
`/api/v1/manufacturing/workflow/production-tools`:

- `/status`: configuration capabilities only; it does not check source connectivity.
- `/projects`: source directory; only `before_id` is accepted.
- `/projects/{source_project_id}/status`: selected source configuration capabilities.
- `/projects/{source_project_id}/observations`
- `/projects/{source_project_id}/catalog/{kind}`
- `/projects/{source_project_id}/evidence`
- `/projects/{source_project_id}/evidence/{source_log_id}/content`
- `/projects/{source_project_id}/statistics`
- `/projects/{source_project_id}/snapshots/{snapshot_id}`

The former manufacturing-project production routes are removed. Source project and
log IDs are decimal strings matching `[1-9][0-9]{0,19}`; preserve them as strings in
browser JSON. Duplicate or unsupported query parameters are rejected.

Trusted process settings:

```text
PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_CONFIG_PATH=/absolute/private/native-production.json
PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_SNAPSHOT_PATH=/absolute/private/production-snapshots-v2.db
```

Use absolute paths. The secret JSON must be owned by the host runtime user or root,
mode 0600 or stricter, regular, nonsymlink and at most 128 KiB. Use a private parent
directory. The host validates that snapshot storage does not alias the private JSON
or any legacy, workflow or authority database, including hardlinks; router initialization
also checks workflow and authority paths. Keep SQLite sidecars in the private directory.
Malformed configuration disables only the optional connector. Diagnostics must never
contain private settings, endpoints, rows or SDK exceptions.

This structural example contains dummy values only:

```json
{
  "version": 2,
  "source_namespace": "orbbec-native-production",
  "revision": "standalone-v2",
  "mysql": {
    "host": "example.invalid", "port": 3306, "user": "readonly-example",
    "password": "EXAMPLE-ONLY", "database": "example"
  },
  "questdb": {
    "host": "example.invalid", "port": 8812, "user": "readonly-example",
    "password": "EXAMPLE-ONLY", "dbname": "qdb"
  },
  "objects": {
    "endpoint": "https://example.invalid", "bucket": "example-bucket",
    "access_key_id": "EXAMPLE-ONLY", "access_key_secret": "EXAMPLE-ONLY",
    "allowed_host": "example.invalid"
  },
  "object_prefixes": {"10001": "logs/10001/"}
}
```

Omit unavailable transports. `version`, `source_namespace`, `revision` and
`object_prefixes` are required; an empty prefix map is allowed. Namespace/revision
use 1–96 letters, digits, underscores or hyphens. Unknown fields, duplicate JSON
keys, legacy version 1, `dataset_id`, manufacturing `project_id` and `bindings` are
rejected. Native SDKs load only when used. No third-party business API is involved.

Select a real source project from MySQL `projuectlists`, with `del=0`, columns `id,name`,
ordered by descending ID. Each directory request reads at most 101 rows and returns
100 with `has_more`/`next_before_id`; the next page is an explicit user action. Do not
loop through the whole directory automatically. Unknown/deleted source projects
return 404 before querying their observations or resolving evidence. Source failure
returns 503, never a fabricated empty directory. MySQL SELECT permission and read-only
transaction support are required. Never infer an object prefix from the project name.
Projects without a confirmed prefix can query records but cannot download objects.

## Bounded verification

Run only under explicit source-read authorization. Commands print transport, query
kind, success, elapsed milliseconds, row count, completeness and a sanitized code.
They never print source rows, credentials, URLs, SQL parameters or exceptions.

```bash
PYTHONPATH=src python scripts/verify_production_tools.py \
  --config /absolute/private/native-production.json \
  --source-project 10001 --transport mysql
PYTHONPATH=src python scripts/verify_production_tools.py \
  --config /absolute/private/native-production.json \
  --source-project 10001 --transport questdb \
  --start 2026-11-09T00:00:00Z --end 2026-11-10T00:00:00Z
```

The CLI checks that the selected source project is active, then defaults to a one-row
capture plus one sentinel. An explicit `--cap` may be 1–1000; HTTP has no cap override.
`--kind` accepts only the transport's fixed catalog, observation or aggregate kinds.
Timed queries require timezone-aware start/end and a range of at most 31 days.
OSS additionally requires `--transport oss --verified-source-log-id 1`, an approved
project prefix and a metadata row in that source project. Content is limited to 10 MiB.
The CLI does not exercise platform authorization; protected HTTP acceptance additionally
requires actual current administrator identity. A successful empty query proves query
execution, not historical business evidence; a TCP handshake alone is insufficient.

## Snapshot semantics and limits

Observations preserve allowed nulls, duplicates and numeric precision, redact source
URLs and dynamic secrets, and report truncation. Captures retain at most 1000 rows and
2 MiB, pages at most 100 rows. There are at most 100 live snapshots per source namespace
and project, 24-hour retention and bounded cleanup of 100 expired entries per capture.
Source timeouts remain five seconds to connect and ten seconds to read/execute, with
four concurrent source operations per worker and no automatic retries. Partial captures
retain `complete=false` and their row/byte reason; time-series partial results have no
invented continuation cursor. MySQL keysets continue from the actual retained last ID.

The independent schema is version 2. Its payload and metadata contain source namespace,
source project and a fingerprint of namespace/project/revision/object prefix; they do
not contain a manufacturing dataset or project UUID. Version 1 caches are rejected
without migration or modification. Use a separate new v2 file. An administrator can
read a valid snapshot while the source is offline; changed scope fingerprints return
404, expiry returns 410 and a new request after administrator downgrade returns 403.
All responses use `Cache-Control: private, no-store`.

Statistics describe records, distinct nonempty SN and PASS-record/all-record ratio;
they do not claim FPY, OEE or finished-goods quantities. `consistency=single_query`
describes one aggregate query, not cross-source atomicity. Activity is not heartbeat.

Rollback removes both optional native settings and restarts the owned host process;
status then reports unconfigured while unrelated workflow remains available. Retain
or remove the separate snapshot file according to the retention process. Never point
it at any business database. No manufacturing schema24 migration, demo cleanup or
source rollback is part of this feature.

## Acceptance boundaries

The socket regression starts a separate loopback uvicorn process with real host identity
middleware and authorization, a synthetic session provider and fake native transports.
It starts with zero manufacturing projects, exercises all nine routes, changes the
provider's current owner role to member between requests and verifies snapshot/download
403 with zero additional source I/O. Set `TEST_PLATFORM_SOURCE_ROOT` to the isolated host
checkout containing the nine-route v2 whitelist before running it.

Credentialed source and protected HTTP acceptance are separate operator-owned work;
synthetic tests do not prove live connectivity. Browser acceptance belongs to the user:
open 产测管理 as an administrator, select a real source project, query an SN, inspect
catalog versions/review orders, download allowed evidence, inspect record statistics,
and reopen a snapshot. Check explicit unavailable states and project-switch stale
response handling. No manufacturing project should need to be created or mapped.

## COPY-only production SDK release profile

The release installer accepts one explicit SDK extension. Omit `native_sdk` to
retain the existing backend/static-only Dockerfile. To opt in, provision
`build/native-sdk/` and `build/native-sdk-manifest.json` in the private payload,
then set `request.native_sdk` to exactly:

```json
{"profile":"native-production-tools-sdk-v1","manifest_sha256":"e4e998c94b019b1d636fafead91e349b9bdbd00d6acff53be5dbf12856505517"}
```

The manifest has exactly `profile`, `python` (`3.11`), `platform`
(`linux-x86_64`), `distributions`, and `files`. Its distributions are exactly
PyMySQL 1.2.4, oss2 2.19.1, crcmod 1.7, pycryptodome 4.4.0,
aliyun-python-sdk-kms 2.16.5, and aliyun-python-sdk-core 2.16.1. The `files`
object maps every SDK-relative file path to its SHA-256. Only the six package
namespaces and their six matching `.dist-info` directories are accepted.
Profile v1 is additionally bound in code to the approved, byte-exact 622-file
manifest SHA-256 `e4e998c94b019b1d636fafead91e349b9bdbd00d6acff53be5dbf12856505517`.
Changing a file, adding a file, or reserializing that manifest requires a new
explicitly reviewed profile; updating only the request pin is insufficient.
The root operator retains the approved tree, trusted wheel provenance and
content-review evidence privately. That review excludes credential payloads
while retaining legitimate upstream code such as
`aliyunsdkcore/auth/credentials.py`. Local synthetic tests explicitly replace
the approved pin only within their test boundary.
Build this tree in disposable Linux preparation against the pinned actual
baseline; preserve wheel hashes and preparation logs privately. Remove bytecode
caches before inventorying. Do not install SDKs into the host or live container.

Generate the Dockerfile with `native_release.dockerfile(baseline_tag, request)`.
The only added instruction is `COPY --chown=0:0 native-sdk/
/usr/local/lib/python3.11/site-packages/` on one line, before the existing two
COPY instructions. The installer checks the actual image-pinned baseline for
namespace/distribution collisions using read-only Python, validates the exact
inventory and metadata versions, then normalizes only the SDK copy tree to
root-owned directories `0755` and files `0644`. The private enclosing stage and
all unrelated files retain their permissions. No build-time network, package
installer, extra image defaults, or additional Dockerfile instructions are
allowed. Prepare pins the manifest and every SDK file. Candidate and deployed
checks read the installed bytes, metadata versions and import origins, verify
Linux x86_64 / Python 3.11, and exercise the CRC64 known vector and Crypto AES extension loading. SDK
execution belongs to the live candidate and post-cutover readiness gates.
Runtime comparison stays inspect-only, including the stopped-target comparison
used by compatible workflow rollback.

Native source settings remain optional. `baseline_native` and `target_native`,
when supplied, each contain exactly these fixed values:

```json
{
  "config_path":"/app/data/manufacturing/native-production-tools/config.json",
  "snapshot_path":"/app/data/manufacturing/native-production-tools/snapshots.sqlite3"
}
```

The release permits only the two explicit environment settings shown above and
uses the existing manufacturing data mount. Existing baseline values must be
preserved exactly. On the host, create only the new `native-production-tools`
subdirectory beneath the existing data directory, owned by `10001:10001` with
mode `0700`. Its configuration and any existing snapshot/SQLite sidecars must
be regular, nonsymlink files owned by `10001:10001` with mode `0600`. The
configuration is at most 128 KiB. Release checks use metadata and a configuration
hash; they do not parse or print credentials. Snapshot inode isolation from the
configuration and the three manufacturing databases is mandatory.

Without approved native source configuration, omit both native path objects and
publish the SDK/code with the source entry closed. Synthetic endpoints and source
IDs must never enter the production configuration. The operator
owns actual-image acceptance and deployment; local helper tests do not establish
live source connectivity or browser acceptance.
