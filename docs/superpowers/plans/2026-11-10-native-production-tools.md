# Native Production Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver 产测管理 with native project-scoped MySQL, QuestDB and OSS reads for SN observations, catalogs, log evidence and record statistics.

**Architecture:** Native Python adapters translate a fixed query contract into source SELECTs, independently of the old application. Existing workflow identity and live project grants govern every read; a separate dataset-bound SQLite store retains bounded immutable observations. React adds a dedicated manufacturing navigation workspace, and the host supplies trusted configuration and exact route whitelisting.

**Tech Stack:** Python >=3.11, existing FastAPI/Pydantic 2/SQLite, PyMySQL, psycopg 3, oss2, React 19/TypeScript/Vitest. Source `productionlog`/`stopoverlog` are QuestDB PGWire; catalog and evidence metadata are MySQL.

## Global Constraints

- Design: `docs/superpowers/specs/2026-11-10-native-production-tools-design.md` is authoritative; the previous `/23790` API bridge transport is superseded.
- App navigation label is **产测管理**; keep **测试与标定** as the existing controlled workflow.
- No old API, old login/JWT, Vue/Go service, third-party repository import/vendor, source initialization or source schema migration.
- Source-side writes, uploads, audit/release/force-release actions, SAP/WMS/MES interfaces and deployment are outside this change.
- Published workflow schema24 and authority schemas remain untouched; snapshots use a separate dataset-bound metadata file.
- Existing platform identity and project authorization are authoritative; source IDs never become platform UUIDs.
- All source business SQL is fixed parameterized bounded SELECT; MySQL read-only transaction control is the only non-SELECT exception.
- QuestDB uses supported PGWire timeout options and an independent fixed query allowlist; do not assume PostgreSQL read-only transaction features work.
- Page size <=100; source capture <=1000 rows plus one sentinel; snapshot payload <=2 MiB; time window <=31 days; attachment <=10 MiB; snapshot lifetime 24 hours.
- Source connect timeout 5 seconds, read/statement timeout 10 seconds, at most 4 concurrent queries per worker; no automatic request retry.
- Preserve permitted source fields/nulls/duplicates; redact arbitrary config `data`/`updatedata`/`launcherdata`, URL fields and credential-named dynamic columns before persistence, explicitly mark redactions and truncation; external observations never upgrade to TestRun, quality release, calibration or manufacturing completion.
- Statistics are records, distinct nonempty SN and PASS-record/all-record ratio; never label these FPY/OEE/completed goods. Recent 5-minute records are activity, not heartbeat.
- Source credentials, private endpoints, source object URLs and row payloads are excluded from committed docs/logs/screenshots.
- Four tasks execute sequentially and receive independent review. Do not commit changes unrelated to the task. User has already authorized implementation; do not add a design approval gate.

---

## File responsibility map

| File | Responsibility |
|---|---|
| `src/manufacturing_platform/production_tools/contracts.py` | Strict public query, trusted binding/config and response contracts |
| `src/manufacturing_platform/production_tools/queries.py` | Fixed SQL registry, value bindings, result normalization |
| `src/manufacturing_platform/production_tools/transports.py` | Native SDK lifetime/timeouts, SQL read and object read transports |
| `src/manufacturing_platform/production_tools/source.py` | Query execution/caps and evidence resolution, no platform authorization |
| `src/manufacturing_platform/production_tools/store.py` | Separate immutable snapshot persistence and dataset validation |
| `src/manufacturing_platform/production_tools/service.py` | Live platform project authorization, binding lookup and snapshot orchestration |
| `src/manufacturing_platform/production_tools/api.py` | Seven routes attached to the existing protected workflow router |
| `src/manufacturing_platform/production_tools/__init__.py` | Explicit exported configuration/factory |
| `webui/src/workflow/productionTools/` | Typed read UI; no domain commands or source credentials |
| Host `backend/app/manufacturing.py`, `manufacturing_paths.py` | Trusted config injection, exact path/method access |

## Shared interfaces (lock before Task 1)

Every task implementer must read `.superpowers/sdd/production-tools-20261110/shared-contracts.md` alongside its extracted task brief; that file contains this global-constraint/interface prefix. A task-only extraction is insufficient context.

Use these public names across task handoffs. Internal helpers may be split without changing the API.

```python
# production_tools/contracts.py
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Callable, Literal, Mapping, Protocol
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceKind = Literal[
    'production', 'stopover', 'software', 'software_versions',
    'configs', 'config_versions', 'review_orders', 'evidence',
    'production_statistics', 'stopover_statistics',
]

class ProductionQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    kind: SourceKind
    start: datetime | None = None
    end: datetime | None = None
    sn: str | None = Field(default=None, min_length=1, max_length=200)
    order_id: str | None = Field(default=None, pattern=r'^[1-9][0-9]{0,19}$')
    device: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal['1', '2'] | None = None
    parent_id: int | None = Field(default=None, ge=1)
    before_id: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def bounded_window(self):
        timed = self.kind in {
            'production', 'stopover', 'evidence',
            'production_statistics', 'stopover_statistics',
        }
        if timed:
            if self.start is None or self.end is None:
                raise ValueError('time range required')
            if self.start.utcoffset() is None or self.end.utcoffset() is None:
                raise ValueError('timezone required')
            seconds = (self.end - self.start).total_seconds()
            if not 0 < seconds <= 31 * 86400:
                raise ValueError('time range must be within 31 days')
        elif self.start is not None or self.end is not None:
            raise ValueError('catalog does not accept a time range')
        if self.kind in {'production', 'stopover', 'production_statistics', 'stopover_statistics'} and self.before_id is not None:
            raise ValueError('source has no verified unique row key')
        return self

@dataclass(frozen=True)
class SourceBinding:
    dataset_id: str
    project_id: UUID
    source_namespace: str
    source_project_id: str
    revision: str
    object_prefix: str

@dataclass(frozen=True)
class ReadStatement:
    name: str
    backend: Literal['mysql', 'questdb']
    sql: str
    params: tuple[Any, ...]
    max_rows: int

class SqlReader(Protocol):
    def select(self, statement: ReadStatement) -> list[dict[str, Any]]: ...

@dataclass(frozen=True)
class EvidenceObject:
    stream: BinaryIO
    size: int | None
    filename: str

class ObjectReader(Protocol):
    def open(self, key: str, *, max_bytes: int) -> EvidenceObject: ...

@dataclass(frozen=True)
class SourceResult:
    source_kind: str
    items: list[dict[str, Any]]
    captured_at: datetime
    filters: dict[str, Any]
    complete: bool
    truncation_reason: str | None
    next_before_id: int | None
    redacted_fields: tuple[str, ...] = ()

class ProductionSource(Protocol):
    @property
    def capabilities(self) -> frozenset[str]: ...
    def query(self, binding: SourceBinding, query: ProductionQuery) -> SourceResult: ...
    def evidence(self, binding: SourceBinding, source_log_id: int, *, before_open: Callable[[], None] | None = None) -> EvidenceObject: ...

@dataclass(frozen=True)
class ProductionToolsConfig:
    source: ProductionSource
    bindings: Mapping[UUID, SourceBinding]
    snapshot_path: str
```

Protocol method ellipses above are Python interface syntax, not deferred work. Implement strict trusted-config validation as well: binding dataset matches host dataset, source project ID is positive decimal text, object prefix is canonical and nonempty for enabled downloads, mapping project keys equal binding UUIDs, revisions are nonempty; duplicate mapping keys fail startup configuration validation. `ProductionToolsConfig` contains an already-constructed source, not raw secrets.

Additional exported signatures:

```python
# queries.py
compile_query(binding: SourceBinding, query: ProductionQuery, *, cap: int = 1000) -> ReadStatement
# source.py
NativeProductionSource(mysql: SqlReader | None, questdb: SqlReader | None, objects: ObjectReader | None, *, allowed_object_host: str, clock: Callable[[], datetime])
# transports.py
build_native_config(config_path: str, snapshot_path: str, dataset: dict[str, str]) -> ProductionToolsConfig
# store.py
SnapshotStore(path: str, dataset: dict[str, str], *, clock: Callable[[], datetime])
SnapshotStore.put(binding: SourceBinding, result: SourceResult) -> UUID
SnapshotStore.get(project_id: UUID, snapshot_id: UUID, binding: SourceBinding, *, offset: int = 0, limit: int = 50) -> dict
# service.py
ProductionToolsService(workflow_store: WorkflowStore, config: ProductionToolsConfig | None, *, clock: Callable[[], datetime])
ProductionToolsService.status(actor: Actor, project_id: UUID) -> dict
ProductionToolsService.query(actor: Actor, project_id: UUID, query: ProductionQuery) -> dict
ProductionToolsService.snapshot(actor: Actor, project_id: UUID, snapshot_id: UUID, *, offset: int = 0, limit: int = 50) -> dict
ProductionToolsService.evidence(actor: Actor, project_id: UUID, source_log_id: int) -> EvidenceObject
# api.py (actor is the existing request-state resolver)
register_production_tools_routes(router: APIRouter, service: ProductionToolsService, actor: Callable[[Request], Actor]) -> None
```

`Callable`, `datetime`, `UUID`, existing `Actor`, `WorkflowStore`, `APIRouter` and `Request` must be imported in their implementing files. The signatures are a contract list, not a Python module to execute verbatim.



## Task 1 clarified native configuration contract

Native JSON has exactly `dataset_id`, optional `mysql`, optional `questdb`, optional `objects`, and `bindings`. `dataset_id` matches the host dataset ID. `mysql` fields are `host`, `port`, `user`, `password`, `database`; `questdb` fields are `host`, `port`, `user`, `password`, `dbname` (default `qdb`); `objects` fields are `endpoint`, `bucket`, `access_key_id`, `access_key_secret`, `allowed_host`. `bindings` is a list of the shared `SourceBinding` fields, with UUID text for project IDs and duplicate platform project IDs rejected. Binding dataset IDs match the top-level and host IDs. Empty object prefix disables downloads for that binding; enabled canonical prefixes end with `/`. Missing backends cause capability-specific unavailability. `ProductionSource.capabilities` is a read-only frozenset of supported SourceKind strings; it additionally contains `evidence_content` only when MySQL and the object reader are configured. The service further disables content for bindings with empty object prefixes. Unsupported kinds fail with `SOURCE_UNAVAILABLE` before attempting I/O. Unknown keys and options overriding enforced connection controls are rejected.

The absolute native secret file is regular, not a symlink, owned by the effective UID or root, and has no group/other permissions. Credentials are absent from repr, errors, snapshots and logs.

Native error codes/status: `SOURCE_UNAVAILABLE`503 for sanitized transport errors, `SOURCE_SCHEMA_INVALID`503 for malformed/upstream out-of-scope rows, `SOURCE_INVALID_QUERY`422 for invalid filters, `SOURCE_LIMIT_EXCEEDED`422 for an oversize first record or unrepresentable bound, `SOURCE_BUSY`503 for exhausted concurrency and `SOURCE_NOT_FOUND`404 for absent/denied evidence. Normal capture truncation is a partial result, not an error. No outward `SOURCE_SCOPE_MISMATCH` containing upstream identifiers.



## Protected status JSON shared with UI

`status` returns `{project_id, configured, capabilities}`. `capabilities` has every SourceKind plus `evidence_content` as keys; each value is `{available: bool, reason: str | null}`. `configured` means this platform project has an explicit valid binding and native config, not that a live connectivity check succeeded. Available entries have null reason. Missing project binding/config uses `PRODUCTION_TOOLS_UNCONFIGURED`; unsupported backend or missing evidence prefix uses `SOURCE_UNAVAILABLE`. Status never performs upstream I/O or returns hosts, source project IDs, namespaces, bucket, prefixes or credentials. UI describes these as configured capabilities, not source health.

### Task 1: Native connectors, source contracts and bounded queries

**Files:**
- Create the package `__init__.py`, `contracts.py`, `queries.py`, `transports.py`, `source.py` listed above.
- Modify `pyproject.toml` optional dependencies.
- Create `tests/production_tools/test_queries.py`, `test_source.py`, `test_transports.py`.

**Interfaces:**
- Consumes the shared contracts and source evidence table in the design; consumes no platform JWT, old-service client or workflow command.
- Produces `ProductionToolsConfig`, `ProductionQuery`, `SourceBinding`, `SourceResult`, `NativeProductionSource`, `compile_query` and `build_native_config` with the exact signatures above.
- `SqlReader.select` is internal, never reachable from API payloads. Native implementations execute only statement names and SQL generated by the fixed compiler; reject unknown registry names and mismatched SQL templates before opening a connection.

- [ ] **Step 1: Add failing tests for a bound SN and fixed project scope.**

```python
from datetime import UTC, datetime
from uuid import UUID
from manufacturing_platform.production_tools.contracts import ProductionQuery, SourceBinding
from manufacturing_platform.production_tools.queries import compile_query

PROJECT = UUID('00000000-0000-4000-8000-000000000001')

def binding():
    return SourceBinding('test', PROJECT, 'fixture', '10001', 'v1', 'logs/10001/')

def test_sn_is_bound_not_interpolated():
    query = ProductionQuery(kind='production', sn="x' OR 1=1 --",
        start=datetime(2026, 11, 9, tzinfo=UTC), end=datetime(2026, 11, 10, tzinfo=UTC))
    statement = compile_query(binding(), query, cap=1000)
    assert statement.backend == 'questdb'
    assert "x' OR 1=1 --" not in statement.sql
    assert '10001' in statement.params
    assert "x' OR 1=1 --" in statement.params
    assert 'projuectid = %s' in statement.sql
    assert statement.max_rows == 1001

def test_catalog_keyset_is_scoped_and_excludes_deleted_rows():
    statement = compile_query(binding(), ProductionQuery(kind='software', before_id=42))
    assert 'projuectid = %s' in statement.sql
    assert 'del = 0' in statement.sql
    assert 'id < %s' in statement.sql
    assert 42 in statement.params
    assert 'ORDER BY id DESC' in statement.sql
```

- [ ] **Step 2: Run red tests.**

Run `python -m pytest tests/production_tools/test_queries.py -q`. Expected failure: missing production_tools package/compiler. Use the existing prepared Python environment; do not confuse a missing pytest installation with the intended red test.

- [ ] **Step 3: Implement contracts and the fixed SQL registry.**

Add the shared contract code. Compiler branches only on `SourceKind` and permitted optional filters. Use static registry values for table names; validate cap 1..1000 before binding cap+1. Do not reproduce the old literal limit/interpolated item-column code. The core QuestDB statement is:

```python
sql = (
    'SELECT * FROM productionlog '
    'WHERE projuectid = %s AND timestamp >= %s AND timestamp < %s'
)
params = [binding.source_project_id, query.start.astimezone(UTC).replace(tzinfo=None),
          query.end.astimezone(UTC).replace(tzinfo=None)]
if query.sn is not None:
    sql += ' AND sn = %s'
    params.append(query.sn)
sql += ' ORDER BY timestamp DESC LIMIT %s'
params.append(cap + 1)
```

Use `stopoverlog` for `stopover`; fixed optional filters bind `orderid`, `devicename`, `status`. Catalog registry:

```python
CATALOG_TABLES = {
    'software': 'softwarelists', 'software_versions': 'softwareversions',
    'configs': 'configlists', 'config_versions': 'configlogs',
    'review_orders': 'orderlists', 'evidence': 'toolslogs',
}
PARENT_FIELDS = {'software_versions': 'softwareid', 'config_versions': 'configid'}
```

Each catalog query contains `WHERE del = 0 AND projuectid = %s`. Bind MySQL project ID as an integer. Bind optional `before_id` in `AND id < %s`, optional allowed parent in `AND softwareid = %s` / `AND configid = %s`, order by `id DESC`, bind cap+1. Reject parent_id for other kinds rather than silently ignoring it. Evidence additionally binds `createtime >= %s AND createtime < %s` using UTC epoch milliseconds, `csn` for SN, `orderid` for order. Reject filters not meaningful to a selected kind. Catalog public projection removes `url`, `url1`, `url2`, `url3`, `data`, `updatedata`, `launcherdata` and records redactions; source retains log URL only while resolving content access.

Statistics use a single aggregate SELECT with the same scope/time/optional predicates:

```sql
SELECT count(*) AS records,
       count_distinct(CASE WHEN sn <> '' THEN sn ELSE null END) AS distinct_sn,
       sum(CASE WHEN status = '1' THEN 1 ELSE 0 END) AS pass_records,
       sum(CASE WHEN status = '2' THEN 1 ELSE 0 END) AS fail_records
FROM productionlog
WHERE projuectid = %s AND timestamp >= %s AND timestamp < %s
```

Normalize null aggregate sums to zero; compute unknown count and nullable record pass ratio. Verify the `count_distinct(CASE...)` expression on the actual QuestDB version; if unsupported, use an equivalent fixed aggregate supported by that server, covered by the same fixtures. Do not aggregate a truncated capture.

- [ ] **Step 4: Add failing adapter tests, then implement native transports and bounded normalization.**

```python
from datetime import UTC, datetime
from manufacturing_platform.production_tools.source import NativeProductionSource

class RecordingReader:
    def __init__(self, rows):
        self.rows, self.calls = rows, []
    def select(self, statement):
        self.calls.append(statement)
        return self.rows[:statement.max_rows]

def test_duplicate_rows_are_preserved_and_truncation_is_honest():
    now = datetime(2026, 11, 10, tzinfo=UTC)
    row = {'timestamp': now, 'projuectid': '10001', 'sn': 'SN-1', 'status': '1'}
    reader = RecordingReader([dict(row) for _ in range(1001)])
    source = NativeProductionSource(reader, reader, None,
        allowed_object_host='example.invalid', clock=lambda: now)
    result = source.query(binding(), ProductionQuery(kind='production',
        start=datetime(2026, 11, 9, tzinfo=UTC), end=now))
    assert len(result.items) == 1000
    assert not result.complete and result.truncation_reason == 'row_limit'
    assert result.next_before_id is None
    assert result.items[0] == result.items[1]
```

Run `python -m pytest tests/production_tools -q` red. Implement `NativeProductionSource.query`: compile, acquire nonblocking semaphore, execute selected reader, validate every returned project's source ID, normalize source datetimes to ISO UTC and Decimal to exact strings, preserve nulls and duplicates, redact URL/config-payload fields and dynamic columns with normalized credential markers (`password`, `passwd`, `secret`, `token`, `credential`, `accesskey`, `privatekey`, `authorization`, `connectionstring`), stop at 1000 rows/2 MiB, return explicit completeness and MySQL continuation. Validate UTF-8 encoded serialized byte size, not Python character count. Reject oversize first row with `SOURCE_LIMIT_EXCEEDED`; do not turn it into a misleading empty success. Normalize status only in a separate display field if useful; never overwrite raw `status`.

Transport lifetime code must have these semantics:

```python
# MySQL reader; approved statement is checked before connect.
connection = connect(connect_timeout=5, read_timeout=10, write_timeout=10,
                     local_infile=False, autocommit=False, **trusted_mysql_options)
try:
    with connection.cursor() as cursor:
        cursor.execute('START TRANSACTION READ ONLY')
        cursor.execute(statement.sql, statement.params)
        rows = cursor.fetchmany(statement.max_rows)
finally:
    try:
        connection.rollback()
    finally:
        connection.close()

# QuestDB reader; don't send PostgreSQL-only read-only session settings.
with connect(autocommit=True, prepare_threshold=None, connect_timeout=5,
             options='-c statement_timeout=10000', **trusted_questdb_options) as connection:
    with connection.cursor() as cursor:
        cursor.execute(statement.sql, statement.params)
        rows = cursor.fetchmany(statement.max_rows)
```

`connect` is injected internally for transport unit tests; real factories import `pymysql.connect` / `psycopg.connect` lazily and use dictionary rows. Trusted option validators must reject collisions with enforced timeout/local-infile/autocommit/options/client-flag settings. Wrap driver errors, including connection construction and session setup failures, without logging their text and map to stable sanitized domain errors; cleanup failures must not replace the sanitized error or prevent connection close. Test closure/rollback after execute and fetch failures and ensure no MySQL source commit. Native source missing required transport affects only its own capability.

Add a redaction test with `data`, `updatedata`, `launcherdata`, `access_key_secret`, `Password`, `url` and a safe `voltage` column; assert only the safe value is returned/persistable and omitted field names are listed. Evidence tests cover cross-project log ID, deleted log, wrong URL host, query-string URL, encoded traversal, absent prefix, oversized/missing-length streams and stream closure. Implement URL parsing using `urllib.parse.urlsplit`, one canonical percent decode, exact allowlisted HTTPS hostname, no explicit port/userinfo/query/fragment and canonical slash-separated prefix. Resolve scoped `toolslogs` row with a fixed SELECT; never use a browser-provided URL. The object transport only calls configured `oss2.Bucket.get_object` and returns a bounded readable stream; it does not create/configure the bucket. Add no object writes.

- [ ] **Step 5: Run Task 1 checks and review the diff.**

Run `python -m pytest tests/production_tools -q`; expected all new connector tests pass. Run `git diff --check`. Inspect `rg -n 'INSERT|UPDATE|DELETE|ALTER|CREATE|23790|requests\.|httpx\.' src/manufacturing_platform/production_tools` and explain every match (there should be no source mutations or HTTP bridge). Source tests must verify fixed statements and runtime bounds rather than relying solely on this textual scan. Review before committing.

- [ ] **Step 6: Commit only Task 1 files.**

```bash
git add pyproject.toml src/manufacturing_platform/production_tools tests/production_tools
git commit -m "feat: add native read-only production data adapters"
```

### Task 2: Project-scoped queries, immutable snapshots and protected evidence API

**Files:**
- Create `production_tools/store.py`, `service.py`, `api.py`.
- Modify `src/manufacturing_platform/workflow/api.py` signature and route registration only.
- Create `tests/production_tools/test_snapshots.py`, `test_api.py`.
- Modify `tests/workflow/conftest.py` to pass optional harness `production_tools` config into router; retain defaults.

**Interfaces:**
- Consumes all Task 1 contracts, `WorkflowStore.transaction()`, `require_project`, existing `Actor` and existing router `PrivateRoute`.
- Produces shared `SnapshotStore`, `ProductionToolsService` and `register_production_tools_routes` signatures, seven exact routes, and the page JSON documented in the design.
- Adds keyword-only `production_tools: ProductionToolsConfig | None = None` to `build_workflow_router`; it remains fully backward compatible when absent.

- [ ] **Step 1: Add failing snapshot isolation/rebinding tests.**

```python
from dataclasses import replace
from datetime import UTC, datetime
import pytest
from manufacturing_platform.production_tools.contracts import SourceResult
from manufacturing_platform.production_tools.store import SnapshotStore
from manufacturing_platform.workflow.contracts import DomainError

def test_snapshot_is_immutable_and_binding_scoped(tmp_path):
    now = datetime(2026, 11, 10, tzinfo=UTC)
    store = SnapshotStore(str(tmp_path / 'observations.db'),
        {'id': 'test', 'mode': 'test', 'label': 'Test'}, clock=lambda: now)
    scope = binding()
    result = SourceResult('production', [{'sn': 'SN-1', 'status': '1'}],
        now, {'sn': 'SN-1'}, True, None, None)
    sid = store.put(scope, result)
    result.items[0]['status'] = '2'
    page = store.get(PROJECT, sid, scope)
    assert page['items'][0]['status'] == '1'
    with pytest.raises(DomainError) as exc:
        store.get(PROJECT, sid, replace(scope, revision='v2'))
    assert exc.value.status == 404
```

Define the `binding()`/`PROJECT` helper in `tests/production_tools/conftest.py` or import the explicitly defined helper from Task 1; do not depend on private implementation fields. Add dataset mismatch, expired snapshot, changed grant, another project UUID, page bounds, row/byte cap and authority/domain path alias cases. Run `python -m pytest tests/production_tools/test_snapshots.py -q`; expected missing store failure.

- [ ] **Step 2: Implement independent snapshot schema and bounded persistence.**

```sql
CREATE TABLE metadata (
  version INTEGER NOT NULL, dataset_id TEXT NOT NULL,
  dataset_mode TEXT NOT NULL, dataset_label TEXT NOT NULL
);
CREATE TABLE snapshots (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
  binding_revision TEXT NOT NULL, source_namespace TEXT NOT NULL,
  source_project_id TEXT NOT NULL, source_kind TEXT NOT NULL,
  captured_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL
);
CREATE INDEX snapshots_project_expiry ON snapshots(project_id, expires_at);
```

Metadata version is 1 and contains exactly one dataset row. Create only a fresh dedicated file; do not repurpose any existing unknown database. Include full effective filters, completeness, redactions and query version in canonical payload JSON. Verify checksum on read. Build the public page from immutable decoded payload and a validated slice; `captured_count` is retained count, not alleged source total. Insert generated UUID and JSON inside one local SQLite transaction, clean at most 100 expired rows on put, enforce <=100 unexpired snapshots per project. Use UTC trusted clock for expiry. Protect metadata file permissions according to existing host deployment convention. Compare configured path to workflow/authority/legacy file paths at composition, including existing `samefile` aliases. No changes to `workflow/schema.py` or its migrations.

- [ ] **Step 3: Add failing HTTP authorization tests.**

Extend the harness `reopen()` call with `production_tools=getattr(self, 'production_tools', None)`. Construct a fake `ProductionSource` that records calls and returns a fixed `SourceResult`, assign config to `workflow.production_tools`, then reopen. The key test body is:

```python
def test_unconfigured_status_is_still_project_scoped(workflow):
    project = workflow.create_project()
    path = f"/api/v1/manufacturing/workflow/projects/{project['id']}/production-tools/status"
    assert workflow.client('outsider').get(path).status_code == 404
    response = workflow.client('owner').get(path)
    assert response.status_code == 200
    assert response.json()['configured'] is False
    assert 'no-store' in response.headers['cache-control']
```

Add configured owner and ordinary member reads, read-only member GET, outsider/no-source-I/O, membership revoked after capture, membership revoked while fake source is paused, mapping revised, wrong project evidence ID, unknown snapshot ID and source failure cases. Assert workflow tests/TestRun/quality-release row counts are unchanged by reads. Run `python -m pytest tests/production_tools/test_api.py -q`; expected missing route or unauthorized behavior failure.

- [ ] **Step 4: Implement service authorization and protected routes.**

Use existing authorization before and after slow source operations:

```python
with self.workflow_store.transaction() as tx:
    require_project(tx, actor, project_id)
binding = self.binding_for(project_id)
result = self.config.source.query(binding, query)
with self.workflow_store.transaction() as tx:
    require_project(tx, actor, project_id)
    self.require_current_binding(project_id, binding)
snapshot_id = self.snapshots.put(binding, result)
return self.snapshot(actor, project_id, snapshot_id)
```

`binding_for` raises `PRODUCTION_TOOLS_UNCONFIGURED` only after authorization; `require_current_binding` compares current binding fields/fingerprint. Implement both as private service methods. `snapshot()` always does a live `require_project` before reading metadata and verifies current binding; an unconfigured status response returns explicit unavailable capabilities and no sensitive topology. `evidence()` passes a `before_open` closure to the source so live membership and current binding are checked again after metadata lookup and immediately before the object reader opens; it also reauthorizes after retrieval. Return sanitized errors and close streams on errors. Test revocation while metadata lookup is paused prevents any object-reader call, and revocation during buffering prevents emission.

Register all seven GET routes from the design directly on the protected workflow router. Use `UUID` path types, positive bounded integer `source_log_id`, and strict `ProductionQuery` construction with rejected unknown query keys. Parse start/end as timezone-aware Pydantic datetimes; enum kinds prevent arbitrary table names. Do not use POST query routes because read-only project members must be able to inspect observations.

Router composition addition:

```python
production_service = ProductionToolsService(store, production_tools,
    clock=store.business_clock)
register_production_tools_routes(router, production_service, actor)
```

Attachment response uses same-origin bytes only, fixed MIME, nosniff and private/no-store. Enforce stream size and source closure in `finally`; do not emit redirects or signed URLs. Check the byte limit before beginning the response when content length is known; for missing length buffer at most 10 MiB+1 before response so an over-cap error is not a truncated successful download. The synchronous read runs off the event loop. Live authorization is repeated immediately before response emission.

- [ ] **Step 5: Verify HTTP and existing workflow compatibility, then commit.**

```bash
python -m pytest tests/production_tools tests/workflow/test_a1_security.py tests/workflow/test_dataset_isolation.py tests/workflow/test_laboratory.py -q
git diff --check
git add src/manufacturing_platform/production_tools src/manufacturing_platform/workflow/api.py tests/production_tools tests/workflow/conftest.py
git commit -m "feat: expose project-scoped production observations and evidence"
```

Expected: all focused tests pass, no schema24 changes, no source I/O before authorization, unknown source failures stay 503 and never become empty snapshots. Review Task 2 before moving to UI.

### Task 3: 产测管理 navigation and usable read workspace

**Files:**
- Modify `webui/src/console/ConsoleShell.tsx` union/icon mapping.
- Modify `webui/src/workflow/WorkflowApp.tsx` explicit nav and dedicated branch.
- Modify `webui/src/workflow/api.ts` typed methods using its existing request/abort/auth machinery.
- Create `webui/src/workflow/productionTools/types.ts`, `ProductionToolsWorkspace.tsx`, `productionTools.css`, `ProductionToolsWorkspace.test.tsx`.
- Modify `webui/src/workflow/navigation.test.tsx` and `api.test.ts`.

**Interfaces:**
- Consumes the seven Task 2 endpoints and exact page JSON. No new transport origin or auth token.
- Produces `ProductionToolsWorkspace({api, projects, initialProjectId?})`; `api` is `ReturnType<typeof createWorkflowApi>`, `projects` is `ProjectDetail[]`.
- API methods: `productionStatus(projectId, signal?)`, `productionObservations(projectId, filters, signal?)`, `productionCatalog(projectId, kind, filters, signal?)`, `productionEvidence(projectId, filters, signal?)`, `productionStatistics(projectId, filters, signal?)`, `productionSnapshot(projectId, snapshotId, offset=0, limit=50, signal?)`, `productionEvidenceUrl(projectId, sourceLogId): string`. Last method constructs only the fixed same-origin protected endpoint, never a source URL.

- [ ] **Step 1: Write failing API URL and navigation regression tests.**

Use existing Vitest setup/React `act`/`createRoot` patterns. The API test must prove encoding and same-origin routing:

```typescript
it('reads production observations from the workflow project scope', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
    JSON.stringify({items: [], snapshot_id: 'snapshot'}), {status: 200}));
  const api = createWorkflowApi({apiBase: '/api/v1/manufacturing', csrfToken: 'csrf'});
  await api.productionObservations('project', {
    kind: 'production', start: '2026-11-09T00:00:00Z', end: '2026-11-10T00:00:00Z',
    sn: 'SN & one',
  });
  const url = String(fetchMock.mock.calls[0][0]);
  expect(url).toContain('/workflow/projects/project/production-tools/observations?');
  expect(new URL(url, location.origin).searchParams.get('sn')).toBe('SN & one');
  api.dispose();
  fetchMock.mockRestore();
});
```

If the existing `MountOptions` requires additional fields, reuse its existing `api.test.ts` options fixture rather than weakening the type. Navigation test renders `WorkflowApp` with its existing bootstrap fixture, clicks **产测管理**, and asserts a project selector plus the four tab labels; it separately proves **测试与标定** still opens its original ledger. Run `npm --prefix webui test -- src/workflow/api.test.ts src/workflow/navigation.test.tsx`; expected new method/nav assertions fail.

- [ ] **Step 2: Add typed API methods and explicit navigation.**

```typescript
// Inside createWorkflowApi's return object; query strings use URLSearchParams.
productionStatus: (id: string, signal?: AbortSignal) =>
  request<ProductionStatus>(p(id) + '/production-tools/status', 'GET', undefined, signal),
productionObservations: (id: string, filters: ObservationFilters, signal?: AbortSignal) =>
  request<ProductionPage>(p(id) + '/production-tools/observations?' +
    new URLSearchParams(Object.entries(filters).filter(([,v]) => v !== undefined)
      .map(([k,v]) => [k, String(v)])), 'GET', undefined, signal),
productionSnapshot: (id: string, snapshotId: string, offset = 0, limit = 50, signal?: AbortSignal) =>
  request<ProductionPage>(p(id) + '/production-tools/snapshots/' + encodeURIComponent(snapshotId) +
    '?' + new URLSearchParams({offset: String(offset), limit: String(limit)}),
    'GET', undefined, signal),
```

Define `ProductionPage` fields exactly as the design page JSON, `ProductionStatus` as sanitized capability statuses, and `ObservationFilters` with kind/start/end plus optional sn/order_id/device/status. Catalog kind is a union of the five specified strings; metadata and statistics calls reuse the same typed encoding helper and request machinery. Evidence URL uses encoded project/id plus the fixed content suffix and rejects nondecimal IDs client-side. Add `| 'production_tools'` to `ConsoleView`, one static icon path, and `["production_tools", "产测管理"]` to `WorkflowApp` navigation. Add the dedicated view branch before generic project/business content:

```tsx
view === 'production_tools' ? (
  <ProductionToolsWorkspace api={api} projects={projects} />
) : (
  /* keep the existing next JSX branch as-is */
)
```

The comment denotes the existing JSX, not a new empty component. Do not add this view to `businessModules`, domain commands or `ObjectKind`.

- [ ] **Step 3: Implement the workspace with controlled selection and bounded tables.**

Use one form for project, start/end and exact SN; four explicit tab buttons; catalog subselect for the five catalog kinds. The selected project must come from `projects`. Load status before issuing source queries; missing selection shows **请选择制造项目**; unconfigured status shows **当前项目尚未配置产测数据源**. Send local datetime input as `new Date(value).toISOString()` and reject invalid/over31-day ranges before request. Show source type, capture UTC rendered locally, applied range, count and **仅显示部分记录，请缩小时间范围或指定 SN** when incomplete. Render metadata with text nodes and `<pre>{JSON.stringify(row, null, 2)}</pre>` details. Evidence rows offer only the fixed controlled content route; no `dangerouslySetInnerHTML`, source URL anchors or data execution. Statistics show the five named counts and nullable ratio, labeled **记录 PASS 比例**.

Use effect cleanup and request generation for race safety:

```typescript
useEffect(() => {
  const controller = new AbortController();
  let current = true;
  setPage(null); setError('');
  if (selectedProjectId) {
    load(controller.signal).then(value => {
      if (current && !controller.signal.aborted) setPage(value);
    }).catch(error => {
      if (current && !controller.signal.aborted) setError(String(error));
    });
  }
  return () => { current = false; controller.abort(); };
}, [selectedProjectId, activeTab, appliedFilters, api]);
```

`load` is the workspace's exhaustive switch over tabs and typed API calls; define it with `useCallback` using the same dependencies or inline it in the effect to satisfy hooks rules. Clear page synchronously when changing projects so prior data is not displayed during a render. Keep draft filters separate from submitted filters. Snapshot next/previous pages call `productionSnapshot`, preserving original capture metadata; MySQL fresh continuation explicitly says **继续读取源记录**. QuestDB partial results offer **缩小范围重新查询**, never a misleading next source page. Auth denial uses existing global retirement; project404 clears local data and gives a project-access message;503 preserves visible query controls and retry. Do not hide errors as zero counts.

- [ ] **Step 4: Add behavioral race, empty, partial and error tests, then verify.**

Deferred-promise test changes project A to B while A is pending, resolves B first then A, and asserts only B rows remain. Mock a partial page with duplicate SN rows and assert both render plus partial label. Mock source503 and assert retry without a zero-record success message. Mock unconfigured status and assert no query method called. Mock revoked404 on snapshot page and assert previous rows cleared. Test narrow viewport through existing CSS responsive conventions and keyboard-accessible labels/buttons.

Run `npm --prefix webui test -- src/workflow/productionTools/ProductionToolsWorkspace.test.tsx src/workflow/navigation.test.tsx src/workflow/api.test.ts`; expected pass. Run `npm --prefix webui run build`; expected TypeScript success and Vite assets. Run `git diff --check`. Review Task 3, then:

```bash
git add webui/src/console/ConsoleShell.tsx webui/src/workflow/WorkflowApp.tsx webui/src/workflow/api.ts webui/src/workflow/api.test.ts webui/src/workflow/navigation.test.tsx webui/src/workflow/productionTools
git commit -m "feat: add production test management workspace"
```

### Task 4: Host wiring, configuration and real socket walkthrough

**Files:**
- In an isolated AI-Agent-Platform worktree: modify `backend/app/manufacturing.py`, `backend/app/manufacturing_paths.py`; extend `backend/tests/test_manufacturing_workflow_bridge.py`; add `backend/tests/test_manufacturing_production_tools.py`.
- In manufacturing worktree: modify `src/manufacturing_platform/__init__.py` to export the native factory; create `docs/runbooks/native-production-tools.md`, `scripts/verify_production_tools.py`, `tests/production_tools/test_socket.py`; extend config parsing tests if host integration reveals a contract gap.
- Update `.superpowers/sdd/production-tools-20261110/progress.md` and sanitized verification report after tests.

**Interfaces:**
- Consumes Task 1 `build_native_config`, Task 2 optional router `production_tools` parameter, seven routes, and Task 3 built assets.
- Produces trusted host configuration via `PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_CONFIG_PATH` and `PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_SNAPSHOT_PATH`; no browser configuration endpoint.
- PF `master` at `3187f834842fcadb50dcbf73a0da918bb4985afb` and its root AGENTS.md were inspected read-only during design; this is the development baseline, not an assertion about running production. Execute changes in a separate host worktree, following its applicable AGENTS.md; never edit/deploy the running production checkout.

- [ ] **Step 1: Write failing host whitelist tests before changing host routes.**

```python
from app.manufacturing_paths import WORKFLOW_ROUTES

def test_production_tools_routes_are_exact_read_routes():
    root = '/projects/{project_id}/production-tools'
    paths = {
        root + '/status', root + '/observations', root + '/catalog/{kind}',
        root + '/evidence', root + '/evidence/{source_log_id}/content',
        root + '/statistics', root + '/snapshots/{snapshot_id}',
    }
    assert {('GET', path) for path in paths} <= WORKFLOW_ROUTES
    assert not any(method != 'GET' and '/production-tools' in path
                   for method, path in WORKFLOW_ROUTES)
```

Run host's documented pytest environment against `backend/tests/test_manufacturing_production_tools.py`; expected missing whitelist assertion. Add enabled, missing-config, malformed-config and unsupported-release-signature tests using existing trusted module loader test patterns. Verify anonymous401, ordinary granted member200, outsider404, GET read-only member200 and unknown methods/paths denied. A malformed optional connector must not disable unrelated workflow.

- [ ] **Step 2: Wire trusted native config without loosening host authorization.**

Add seven exact tuples to `WORKFLOW_ROUTES`. Because unavailable routers already iterate that set, verify each path returns authenticated503 when the whole workflow is unavailable. Extend host loader only if `build_workflow_router` exposes the optional keyword. Export `build_native_config` from the manufacturing package (lazy import permitted). Host passes a native config object in `profile_options`:

```python
config_path = os.environ.get('PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_CONFIG_PATH', '')
snapshot_path = os.environ.get('PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_SNAPSHOT_PATH', '')
if config_path or snapshot_path:
    if not config_path or not snapshot_path:
        production_config = None
    else:
        production_config = module.build_native_config(
            config_path, snapshot_path,
            {'id': dataset_id, 'mode': mode, 'label': label},
        )
    profile_options['production_tools'] = production_config
```

Catch native configuration errors in a separate optional-connector boundary, sanitize diagnostics and pass unconfigured status while leaving workflow available. If the loaded release lacks the keyword/factory, leave connector unavailable and report version incompatibility without compromising existing workflow. Do not catch errors by enabling an old API bridge. Validate the two absolute paths and snapshot separation from all existing host DBs before construction. Native config loader enforces secret-file ownership/permissions using host conventions and never prints file contents. Runtime reads our own native configuration only, never third-party TOML or files under `analysis-repos`. Parse only explicit known keys; settings can't override SQL registry, timeouts or project auth.

Runbook provides a credential-free structural example with `example.invalid`, dummy dataset/project/source IDs and documented secret-file permissions. Require source bindings be approved as actual project mappings; do not infer mapping by matching display names. Document read-only account support verification, object-prefix verification, partial-snapshot semantics, source unavailability, expiry, retention and rollback by removing native settings. No account creation or grants are performed by this task.

- [ ] **Step 3: Add a real local HTTP socket regression before live-source checks.**

`test_socket.py` starts an isolated FastAPI app with existing workflow router, fake native transports and temp files on a free loopback port using the host's installed ASGI runner. It must issue actual HTTP requests (not only TestClient) for authorized/unconfigured/status/query/snapshot/evidence paths and revoke a real test grant before re-reading a snapshot. Use subprocess lifecycle/timeout cleanup and bounded polling, never static sleeps. Test fixture source rows stay synthetic. Assert no source reads for outsider, correct no-store/nosniff, retained duplicate rows and revoked snapshot404. Repeat one normal workflow endpoint to prove integration isolation.

`verify_production_tools.py` accepts trusted config path and explicit project UUID, supports `--transport mysql|questdb|oss` and `--start/--end`, reuses the native compiler/adapters, and prints only transport, query kind, success, elapsed time, row count, completeness and sanitized error code. It has no arbitrary SQL/table/URL flag. Default cap is 1; OSS verification is opt-in and requires a verified source log ID in that same binding. No source mutation or source initialization is reachable. Do not print rows, SQL params, credentials, raw URLs or source exceptions.

- [ ] **Step 4: Run source socket checks and prepare the user browser walkthrough, documenting actual results.**

Reuse root's already successful direct MySQL/QuestDB probe evidence where it establishes an unchanged compatibility fact; do not repeat those probes without a new adapter/configuration concern. Verify newly implemented adapters with credentialed native MySQL scoped catalog SELECT, scoped evidence metadata SELECT, QuestDB scoped test and passage SELECT plus one aggregate within a one-day window. Verify actual timestamp units/columns/status values without copying row payloads into reports. Verify no legacy service is needed. If configured OSS credentials and project prefix are verified, read one bounded object through the protected platform route; otherwise mark only controlled download as unverified/unavailable. A TCP handshake alone is not a successful query. A successful query with zero rows proves connectivity/query execution, not the presence of historical business evidence.

Start a local host HTTP process using the isolated snapshot DB and native adapters and verify its authorized endpoints over a real socket. PF root AGENTS.md assigns browser/page acceptance to the user; do not autonomously open a browser without newer explicit user authorization. Provide the user this walkthrough: open **产测管理**, select a mapped project, execute SN query, review catalog versions/review-order wording, download one permitted evidence item if available, read record statistics, navigate a snapshot and confirm no quality/work-order action appeared. Test the unavailable path explicitly. Retain sanitized API/component check results and identify browser acceptance as user-owned/pending; no production deployment.

- [ ] **Step 5: Run final verification and commit separately in each repository.**

Manufacturing commands:

```bash
python -m pytest tests/production_tools tests/workflow/test_a1_security.py tests/workflow/test_dataset_isolation.py tests/workflow/test_laboratory.py -q
npm --prefix webui test
npm --prefix webui run test:bundle
git diff --check
```

Host commands use its documented environment and run `backend/tests/test_manufacturing_production_tools.py`, `backend/tests/test_manufacturing_workflow_bridge.py`, `backend/tests/test_manufacturing_bridge.py`, `backend/tests/test_manufacturing_member_profiles.py`. Expected all relevant tests pass. Inspect final diffs for source credentials, schema24 mutation and old bridge code. Record source probes separately from fixture/socket tests. Commit host wiring and manufacturing runbook/verification changes independently after review; do not stage unrelated root-worktree files or deploy.

## Self-review and execution handoff

Coverage: Task1 implements all four native source read families and guarded SDKs; Task2 implements identity/mapping/snapshot/evidence access; Task3 supplies actual navigation and all four user flows; Task4 closes strict host routes, trusted settings and real socket evidence. No source credential values or private endpoints appear in this plan. QuestDB source-order uncertainty, missing unique row key, unsupported read-only transaction controls, zero denominators and source partial failures have explicit handling.

Execute sequentially under the user's existing authorization. Each task's reviewer can reject that task without invalidating earlier native interfaces. The user already asked to start native development, so the standard skill execution-choice question is unnecessary. If source-specific compatibility differs from documented evidence, update the narrow adapter and its tests, report the limitation and preserve the authorization/source-write boundaries.

Evidence authorization handoff: `ProductionSource.evidence` accepts optional `before_open`. Native source invokes it after the scoped MySQL lookup and URL/prefix validation, immediately before object-reader open; authorization exceptions propagate and no object is opened. The service passes a closure that reauthorizes live membership and the current binding. Test fakes honor the same callback. API repeats live authorization after bounded buffering and before response emission. This closes the existing design boundary between potentially slow metadata I/O and OSS opening.
