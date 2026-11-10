"""Explicit, bounded native adapter probe. Never prints source rows or settings."""

import argparse
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from manufacturing_platform import build_native_config
from manufacturing_platform.production_tools.contracts import (
    ProductionQuery,
    SourceScope,
)
from manufacturing_platform.production_tools.source import MAX_ATTACHMENT
from manufacturing_platform.workflow.contracts import DomainError

KINDS = {
    "mysql": (
        "software",
        "software_versions",
        "configs",
        "config_versions",
        "review_orders",
        "evidence",
    ),
    "questdb": (
        "production",
        "stopover",
        "production_statistics",
        "stopover_statistics",
    ),
    "oss": ("evidence_content",),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--source-project", required=True)
    parser.add_argument("--transport", choices=tuple(KINDS), required=True)
    parser.add_argument("--kind")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--cap", type=int, default=1)
    parser.add_argument("--verified-source-log-id", type=int)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[1-9][0-9]{0,19}", args.source_project):
        parser.error("source project must be a decimal ID of 1 to 20 digits")
    kind = args.kind or KINDS[args.transport][0]
    if kind not in KINDS[args.transport] or not 1 <= args.cap <= 1000:
        parser.error("invalid query kind or capture cap")
    if args.transport == "oss" and (
        args.verified_source_log_id is None
        or not 1 <= args.verified_source_log_id <= 99999999999999999999
    ):
        parser.error(
            "OSS requires an approved log ID within the selected source project"
        )
    if args.transport != "oss" and args.verified_source_log_id is not None:
        parser.error("log ID is only supported for explicit OSS verification")
    if not Path(args.config).is_absolute():
        parser.error("config path must be absolute")
    summary = {
        "transport": args.transport,
        "query_kind": kind,
        "success": False,
        "elapsed_ms": 0,
        "row_count": 0,
        "complete": False,
        "error_code": None,
    }
    started = monotonic()
    try:
        with TemporaryDirectory(prefix="native-production-verify-") as directory:
            config = build_native_config(
                args.config,
                str(Path(directory) / "snapshot.db"),
            )
            binding = SourceScope(
                config.source_namespace,
                args.source_project,
                config.revision,
                config.object_prefixes.get(args.source_project, ""),
            )
            config.source.project(args.source_project)
            if args.transport == "oss":
                if args.start or args.end:
                    raise ValueError("unexpected time range")
                opened = config.source.evidence(binding, args.verified_source_log_id)
                try:
                    count = 0
                    while True:
                        chunk = opened.stream.read(
                            min(65536, MAX_ATTACHMENT + 1 - count)
                        )
                        count += len(chunk)
                        if count > MAX_ATTACHMENT:
                            raise ValueError("object limit")
                        if not chunk:
                            break
                    if opened.size is not None and count != opened.size:
                        raise ValueError("object size")
                finally:
                    opened.stream.close()
                summary.update(success=True, row_count=1, complete=True)
            else:
                query = ProductionQuery(kind=kind, start=args.start, end=args.end)
                result = config.source.query(binding, query, cap=args.cap)
                summary.update(
                    success=True, row_count=len(result.items), complete=result.complete
                )
    except Exception as exc:  # noqa: BLE001 - source exceptions and config errors may contain secrets
        allowed = {
            "SOURCE_UNAVAILABLE",
            "SOURCE_SCHEMA_INVALID",
            "SOURCE_LIMIT_EXCEEDED",
            "SOURCE_NOT_FOUND",
            "SOURCE_BUSY",
            "SOURCE_INVALID_QUERY",
        }
        summary["error_code"] = (
            exc.code
            if isinstance(exc, DomainError) and exc.code in allowed
            else "VERIFICATION_UNAVAILABLE"
        )
    summary["elapsed_ms"] = round((monotonic() - started) * 1000, 2)
    print(json.dumps(summary, separators=(",", ":")))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
