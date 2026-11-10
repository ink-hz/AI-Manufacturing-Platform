# Native production tools

产测管理 reads external observations through native adapters. The host's existing
session and live project grants authorize every route, including snapshot reads
and evidence downloads. No source account, grant, bucket or table is created.
The separate 测试与标定 workflow remains the controlled business workflow.

## Host configuration

Use a release containing `build_native_config`, `validate_snapshot_path` and the
optional `production_tools` workflow keyword. The host permits exactly seven GET
routes under `/api/v1/manufacturing/workflow/projects/{project_id}/production-tools`:
`status`, `observations`, `catalog/{kind}`, `evidence`,
`evidence/{source_log_id}/content`, `statistics`, `snapshots/{snapshot_id}`.
Older releases return authenticated 503 on missing routes; existing workflow
routes remain available. Anonymous requests return 401. Unmapped/unauthorized
projects remain unavailable to outsiders, without source reads.

Trusted process settings:

```text
PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_CONFIG_PATH=/absolute/private/native-production.json
PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_SNAPSHOT_PATH=/absolute/private/production-snapshots.db
```

Both paths must be absolute. Keep the secret JSON owned by the host runtime user
(or root), with mode `0600` or stricter and a private parent directory; symlinks,
nonregular files, group/world permissions and files over 128 KiB are rejected.
Snapshot storage must resolve to a separate file from the actual host legacy,
workflow and authority databases and the secret JSON; hardlink aliases are also
rejected. Keep snapshot storage and its SQLite sidecars in a private directory.
The host validates these paths before constructing the native configuration.
Missing halves or malformed settings disable only this connector. Diagnostics
use fixed codes, never raw configuration or SDK exceptions.

This structural example uses dummy values only; replace it through the trusted
secret-management process, never through browser configuration:

```json
{
  "dataset_id": "example-dataset",
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
  "bindings": [{
    "dataset_id": "example-dataset",
    "project_id": "00000000-0000-4000-8000-000000000001",
    "source_namespace": "example-native", "source_project_id": "10001",
    "revision": "approved-example-v1", "object_prefix": "logs/10001/"
  }]
}
```

Omit unavailable transports. Unknown keys cannot override SQL, timeouts or
project authorization. Host runtime packaging pins PyMySQL 1.2.4, psycopg 3.3.4
(cloud) and oss2 2.19.1. SDKs load only when their capability is used. Runtime
reads this native JSON only; no third-party application's settings, service,
login token or repository is required.

Before enabling a binding, its owner must approve the exact platform project UUID,
source project ID, dataset, namespace, revision and object prefix as a real mapping.
Never infer mappings from matching display names. Verify that the database account
supports scoped SELECT and MySQL `START TRANSACTION READ ONLY`; unsupported controls
fail closed. Confirm QuestDB PGWire compatibility, timestamps, columns and status
values through bounded queries. Check OSS account permissions and the exact object
prefix before enabling controlled download. Account creation and grants are an
operator responsibility outside this implementation.

## Bounded verification

Run from the manufacturing release with its dependencies available. These explicit
commands print only transport, query kind, success, elapsed milliseconds, row count,
completeness and sanitized error code. They never print rows, credentials, URLs,
SQL parameters or source exceptions. No arbitrary SQL, table or URL flag exists.

```bash
PYTHONPATH=src python scripts/verify_production_tools.py \
  --config /absolute/private/native-production.json --dataset-id example-dataset \
  --project 00000000-0000-4000-8000-000000000001 --transport mysql
PYTHONPATH=src python scripts/verify_production_tools.py \
  --config /absolute/private/native-production.json --dataset-id example-dataset \
  --project 00000000-0000-4000-8000-000000000001 --transport questdb \
  --start 2026-11-09T00:00:00Z --end 2026-11-10T00:00:00Z
```

The default capture cap is **1**, implemented in the SELECT limit/fetch bound
with one additional sentinel; it does not fetch 1000 rows and hide them. An explicit
trusted CLI `--cap` may be 1–1000. HTTP does not expose a cap override. `--kind` is
restricted to that transport's fixed catalog/observation/aggregate kinds. Timed
queries require timezone-aware start/end, maximum 31 days; prefer a one-day window.
A statistics query returns one aggregate row and declares `consistency=single_query`;
this does not promise cross-source atomicity. A successful zero-row query establishes
connectivity/execution, not historical business evidence. A TCP handshake is insufficient.

OSS is opt-in via `--transport oss --verified-source-log-id 1`, only after that exact
log ID and prefix have been approved in the selected binding. It resolves scoped
metadata and validates the host/prefix before one bounded object read (10 MiB maximum).
No object upload or initialization is reachable. If OSS credentials or prefix cannot
be verified, mark controlled download unverified/unavailable; other transports can
still be used. This CLI does not exercise platform session authorization; protected
HTTP acceptance must additionally use actual project grants and current membership.

## Semantics, retention and rollback

Observation captures preserve allowed nulls and duplicates, redact dynamic secret
fields and source URLs, and record truncation. Snapshots capture at most 1000 rows
plus a sentinel, total payload at most 2 MiB; page size is at most 100. Partial captures
must retain `complete=false` and their row/byte limit reason. A source failure is an
unavailable capability/error, never an empty successful result. Queries use five-second
connect and ten-second read/statement timeouts, at most four concurrent source operations
per worker, with no automatic retries. External observations never create TestRun,
quality release, calibration, work-order or completion facts.

Statistics describe records, distinct nonempty SN and PASS-record/all-record ratio;
they do not measure FPY, OEE or completed goods. Five-minute activity is not heartbeat.
Snapshots expire after 24 hours; expired rows are pruned in bounded batches during new captures. Keep no
longer retention through backups/exports unless separately approved. Live grant
revocation and changed bindings invalidate access, including retained snapshots.

Rollback removes both native environment settings and restarts the owned host process.
The status endpoint then reports unconfigured, with unrelated workflow intact. Retain or
remove the isolated snapshot file according to the approved retention process; never
point it at a workflow/authority/legacy file. No source rollback or schema migration exists.

## Acceptance boundaries

The synthetic socket regression runs a separate local uvicorn process, real host
identity middleware/authorization and real project grant/revoke commands, with explicitly
synthetic session provider and native transport rows. It checks duplicates, snapshot
revocation, unauthorized no-I/O, unavailable isolation and download headers. Run it with
`TEST_PLATFORM_SOURCE_ROOT` selecting the isolated host checkout.

Live adapters/protected routes require a separate credentialed acceptance report; do
not describe synthetic tests as live source validation. Root/controller owns that phase.
Browser acceptance belongs to the user: open **产测管理**, select an approved mapped
project, execute an SN query, inspect catalog versions/review-order wording, download
one permitted evidence item if available, review record statistics, reopen a snapshot,
and confirm no quality/work-order actions appeared. Check the explicit unavailable
state. Browser and production deployment are not performed by this task.
