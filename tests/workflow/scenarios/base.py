"""Immutable, pytest-independent acceptance execution and evidence."""

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import importlib.metadata
import platform
import json
from pathlib import Path
import sqlite3
import time
import traceback
from threading import Lock
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from . import ScenarioRegistry, EXPECTATIONS

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CLOCK = "2026-10-28T00:00:00+00:00"
SEED_VERSION = "workflow-complete-v1"
OWNER = "manufacturing-workflow-acceptance-v1"


def redact(value):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if k.lower().replace("_", "-")
            in {
                "cookie",
                "set-cookie",
                "authorization",
                "secret",
                "csrf",
                "x-csrf-token",
                "password",
                "token",
            }
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(
            redact(value),
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        stream.write("\n")


def source_manifest():
    from .provenance import source_manifest as collect

    return collect(ROOT)


class EvidenceWriter:
    def __init__(self, directory):
        self.directory, self.sequence = Path(directory), 0
        self.artifacts = []
        self.lock = Lock()

    def record(self, kind, value):
        with self.lock:
            self.sequence += 1
            path = self.directory / f"{self.sequence:06}-{kind}.json"
            write_new(
                path,
                {
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "kind": kind,
                    "value": value,
                },
            )
            self.artifacts.append(str(path))
            return path

    def record_request(self, value):
        return self.record("request", value)

    def record_response(self, value):
        return self.record("response", value)

    def _snapshot(self, path, kind):
        path = Path(path)
        if not path.exists():
            return self.record(kind, {"exists": False, "path": str(path)})
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            tables = [
                r[0]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            result = {
                table: [
                    dict(r)
                    for r in db.execute(
                        'SELECT * FROM "' + table.replace('"', '""') + '"'
                    )
                ]
                for table in tables
            }
        return self.record(kind, {"path": str(path), "tables": result})

    def record_db_snapshot(self, path):
        return self._snapshot(path, "workflow-db")

    def record_authority_snapshot(self, path):
        return self._snapshot(path, "authority-db")

    def finish(self, result):
        write_new(self.directory / "result.json", asdict(result))


@dataclass(frozen=True)
class ScenarioPaths:
    domain: Path
    authority: Path
    legacy: Path


@dataclass
class ScenarioContext:
    run_id: str
    case_id: str
    seed: int
    clock: datetime
    client: object
    paths: ScenarioPaths
    evidence: EvidenceWriter
    expected: dict = field(default_factory=dict)
    actual: dict = field(default_factory=dict)
    operation_ids: list = field(default_factory=list)
    object_ids: list = field(default_factory=list)
    counter: int = 0

    @property
    def directory(self):
        return self.paths.domain.parent

    @property
    def dataset_id(self):
        return f"{self.run_id}-{self.case_id}"

    def identifier(self, label):
        self.counter += 1
        return str(
            uuid5(
                NAMESPACE_URL,
                f"{SEED_VERSION}:{self.seed}:{self.case_id}:{label}:{self.counter}",
            )
        )

    @classmethod
    def isolated(
        cls, output, *, case_id, seed, clock=DEFAULT_CLOCK, resume=None, run_id=None
    ):
        ScenarioRegistry.validate(case_id)
        output = Path(output)
        if not output.is_absolute():
            raise ValueError("Output directory must be absolute")
        value = (
            datetime.fromisoformat(clock.replace("Z", "+00:00"))
            if isinstance(clock, str)
            else clock
        )
        if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("Business clock must be UTC")
        if resume is not None:
            previous = owned_run(Path(resume))
            if previous["case_id"] != case_id:
                raise ValueError("Resume case must match failed case")
            result = json.loads((Path(resume) / "result.json").read_text())
            if result["status"] not in {"failed", "blocked"}:
                raise ValueError("Resume requires failed or blocked evidence")
        provenance = source_manifest()
        run_id = run_id or f"run-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex}"
        directory = output / run_id / case_id
        directory.mkdir(parents=True, exist_ok=False)
        paths = ScenarioPaths(
            directory / "workflow.db",
            directory / "authority.db",
            directory / "legacy.db",
        )
        context = cls(
            run_id,
            case_id,
            seed,
            value,
            None,
            paths,
            EvidenceWriter(directory),
            expected={"required_end_state": EXPECTATIONS[case_id]},
        )
        context.business_source_root = provenance["business_source_root"]
        write_new(
            directory / "manifest.json",
            {
                "owner": OWNER,
                "directory": str(directory),
                "run_id": run_id,
                "case_id": case_id,
                "dataset_id": context.dataset_id,
                "dataset_mode": "test",
                "seed": seed,
                "seed_version": SEED_VERSION,
                "business_clock": value.isoformat(),
                "source": provenance,
                "runtime": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "sqlite": sqlite3.sqlite_version,
                    "packages": {
                        name: importlib.metadata.version(name)
                        for name in ("fastapi", "starlette", "pydantic", "uvicorn")
                    },
                },
                "resumes": str(resume) if resume else None,
                "auth_fixture_boundary": {
                    "transport": "server-session-cookie-and-CSRF",
                    "identities": "synthetic-test-only",
                    "security_clock": "actual-UTC",
                },
                "external_cost_boundary": "manual recording of synthetic external ERP cost-close receipt; append-only receipt artifact with identity/time/signatory/file hash; no ERP API or accounting voucher",
                "authority_fault_config": {
                    "initial": "none",
                    "changes": "append-only authority-boundary request artifacts",
                },
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
        return context


@dataclass
class CaseResult:
    id: str
    status: Literal["passed", "failed", "blocked", "not_executed"]
    duration_ms: int
    expected: dict
    actual: dict
    operation_ids: list
    object_ids: list
    artifact_paths: list
    error: str | None


class ScenarioBlocked(RuntimeError):
    pass


ScenarioStep = Callable[[ScenarioContext], None]


def owned_run(directory):
    path = Path(directory)
    if path.is_symlink() or not path.is_absolute() or (path / "manifest.json").is_symlink():
        raise ValueError("Not an owned run directory")
    try:
        manifest = json.loads((path / "manifest.json").read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("Not an owned run directory") from exc
    if (
        manifest.get("owner") != OWNER
        or manifest.get("dataset_mode") not in {"test", "demo"}
        or manifest.get("directory") != str(path)
    ):
        raise ValueError("Not an owned test/demo run directory")
    return manifest


def exception_location(exc):
    # Frame metadata only: no locals, source lines, exception repr or chained payloads.
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "frames": [
            {"file": frame.filename, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(exc.__traceback__)
        ],
    }


def run_case(
    context: ScenarioContext, steps: Sequence[ScenarioStep] | None = None
) -> CaseResult:
    # Exclusive claim precedes any action, including process/session creation.
    with (context.directory / "started.json").open("x") as stream:
        json.dump({"started_at": datetime.now(UTC).isoformat()}, stream)
    start = time.monotonic()
    status, error = "passed", None
    try:
        actions = (
            steps if steps is not None else [ScenarioRegistry.get(context.case_id)]
        )
        for action in actions:
            context.evidence.record("step", {"name": action.__name__})
            action(context)
    except ScenarioBlocked as exc:
        status, error = "blocked", str(exc)
    except Exception as exc:
        status, error = "failed", str(exc)
        context.evidence.record("failure", exception_location(exc))
    finally:
        cleanup = ([context.client.close] if context.client is not None else []) + [
            lambda: context.evidence.record_db_snapshot(context.paths.domain),
            lambda: context.evidence.record_authority_snapshot(context.paths.authority),
        ]
        for operation in cleanup:
            try:
                operation()
            except Exception as exc:
                context.evidence.record(
                    "teardown-failure",
                    exception_location(exc),
                )
                if error is None:
                    status, error = "failed", str(exc)
    result = CaseResult(
        context.case_id,
        status,
        int((time.monotonic() - start) * 1000),
        context.expected,
        context.actual,
        context.operation_ids,
        context.object_ids,
        context.evidence.artifacts.copy(),
        error,
    )
    context.evidence.finish(result)
    return result
