"""Fixed statement registry. No SQL identifiers come from input values."""

from datetime import UTC, datetime
from itertools import combinations

from .contracts import ProductionQuery, ReadStatement, SourceScope, valid_source_id

CATALOG_TABLES = {
    "software": "softwarelists",
    "software_versions": "softwareversions",
    "configs": "configlists",
    "config_versions": "configlogs",
    "review_orders": "orderlists",
    "evidence": "toolslogs",
}
PARENT_FIELDS = {"software_versions": "softwareid", "config_versions": "configid"}
LOG_TABLES = {"production": "productionlog", "stopover": "stopoverlog"}
AGGREGATE = (
    "count(*) AS records, count_distinct(CASE WHEN sn <> '' THEN sn ELSE null END) AS distinct_sn, "
    "sum(CASE WHEN status = '1' THEN 1 ELSE 0 END) AS pass_records, "
    "sum(CASE WHEN status = '2' THEN 1 ELSE 0 END) AS fail_records"
)
EVIDENCE_SQL = "SELECT id, projuectid, del, url FROM toolslogs WHERE del = 0 AND projuectid = %s AND id = %s LIMIT %s"


def _template(kind, filters):
    statistics = kind.endswith("_statistics")
    base = kind.removesuffix("_statistics")
    if base in LOG_TABLES:
        sql = f"SELECT {AGGREGATE if statistics else '*'} FROM {LOG_TABLES[base]} WHERE projuectid = %s AND timestamp >= %s AND timestamp < %s"
        fields = {
            "sn": "sn",
            "order_id": "orderid",
            "device": "devicename",
            "status": "status",
        }
    else:
        sql = f"SELECT * FROM {CATALOG_TABLES[kind]} WHERE del = 0 AND projuectid = %s"
        if kind == "evidence":
            sql += " AND createtime >= %s AND createtime < %s"
        fields = {
            "before_id": "id",
            "parent_id": PARENT_FIELDS.get(kind),
            "sn": "csn",
            "order_id": "orderid",
        }
    for field in filters:
        sql += f" AND {fields[field]} {'<' if field == 'before_id' else '='} %s"
    if not statistics:
        sql += (
            " ORDER BY timestamp DESC LIMIT %s"
            if base in LOG_TABLES
            else " ORDER BY id DESC LIMIT %s"
        )
    return sql


def allowed_filters(kind):
    if kind.removesuffix("_statistics") in LOG_TABLES:
        return ("sn", "order_id", "device", "status")
    return (
        ("before_id",)
        + (("parent_id",) if kind in PARENT_FIELDS else ())
        + (("sn", "order_id") if kind == "evidence" else ())
    )


def _ceil_epoch_milliseconds(date: datetime) -> int:
    # Source timestamps are integer milliseconds; both half-open thresholds round up.
    delta = date.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    microseconds = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    return -(-microseconds // 1000)


def compile_query(
    binding: SourceScope, query: ProductionQuery, *, cap: int = 1000
) -> ReadStatement:
    if type(cap) is not int or not 1 <= cap <= 1000:
        raise ValueError("invalid capture cap")
    allowed = allowed_filters(query.kind)
    for name in ("sn", "order_id", "device", "status", "parent_id", "before_id"):
        if getattr(query, name) is not None and name not in allowed:
            raise ValueError("unsupported source filter")
    log = query.kind.removesuffix("_statistics") in LOG_TABLES
    params = [binding.source_project_id if log else int(binding.source_project_id)]
    if query.start is not None:
        if log:
            params += [
                date.astimezone(UTC).replace(tzinfo=None)
                for date in (query.start, query.end)
            ]
        else:
            params += [
                _ceil_epoch_milliseconds(date) for date in (query.start, query.end)
            ]
    filters = tuple(name for name in allowed if getattr(query, name) is not None)
    params += [getattr(query, name) for name in filters]
    statistics = query.kind.endswith("_statistics")
    if not statistics:
        params.append(cap + 1)
    return ReadStatement(
        query.kind,
        "questdb" if log else "mysql",
        _template(query.kind, filters),
        tuple(params),
        1 if statistics else cap + 1,
    )


def evidence_statement(binding: SourceScope, source_log_id: int) -> ReadStatement:
    if type(source_log_id) is not int or source_log_id < 1:
        raise ValueError("invalid source log id")
    return ReadStatement(
        "evidence_object",
        "mysql",
        EVIDENCE_SQL,
        (int(binding.source_project_id), source_log_id, 2),
        2,
    )


DIRECTORY_SQL = {
    "source_projects": "SELECT id, name FROM projuectlists WHERE del = 0 ORDER BY id DESC LIMIT %s",
    "source_projects_before": "SELECT id, name FROM projuectlists WHERE del = 0 AND id < %s ORDER BY id DESC LIMIT %s",
    "source_project": "SELECT id, name FROM projuectlists WHERE del = 0 AND id = %s LIMIT %s",
}


def directory_statement(*, before_id=None, source_project_id=None):
    value = source_project_id if source_project_id is not None else before_id
    if value is not None and not valid_source_id(value):
        raise ValueError("invalid source project id")
    name = (
        "source_project"
        if source_project_id is not None
        else "source_projects_before"
        if before_id is not None
        else "source_projects"
    )
    cap = 2 if source_project_id is not None else 101
    return ReadStatement(
        name,
        "mysql",
        DIRECTORY_SQL[name],
        (int(value), cap) if value is not None else (cap,),
        cap,
    )


def validate_statement(statement: ReadStatement) -> None:
    """Validate registry name, backend, exact SQL shape and bounded result count before I/O."""
    if statement.name in DIRECTORY_SQL:
        cap = 2 if statement.name == "source_project" else 101
        valid = (
            statement.backend == "mysql"
            and statement.sql == DIRECTORY_SQL[statement.name]
            and statement.max_rows == cap
            and len(statement.params) == statement.sql.count("%s")
            and statement.params[-1] == cap
            and all(
                type(value) is int and 1 <= value <= 99999999999999999999
                for value in statement.params
            )
        )
    elif statement.name == "evidence_object":
        valid = (
            statement.backend == "mysql"
            and statement.sql == EVIDENCE_SQL
            and statement.max_rows == 2
            and len(statement.params) == 3
            and statement.params[-1] == 2
        )
    elif statement.name in {
        *LOG_TABLES,
        *CATALOG_TABLES,
        "production_statistics",
        "stopover_statistics",
    }:
        log = statement.name.removesuffix("_statistics") in LOG_TABLES
        names = allowed_filters(statement.name)
        templates = {
            _template(statement.name, subset)
            for length in range(len(names) + 1)
            for subset in combinations(names, length)
        }
        stats = statement.name.endswith("_statistics")
        valid = (
            statement.sql in templates
            and statement.backend == ("questdb" if log else "mysql")
            and type(statement.max_rows) is int
            and (statement.max_rows == 1 if stats else 2 <= statement.max_rows <= 1001)
            and len(statement.params) == statement.sql.count("%s")
            and (stats or statement.params[-1] == statement.max_rows)
        )
    else:
        valid = False
    if not valid:
        raise ValueError("unapproved source statement")
