#!/usr/bin/env python3
"""Private source-tree acceptance entrypoint; no pytest or server reset endpoint."""

import argparse
from dataclasses import asdict
from datetime import datetime, UTC
import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]
from workflow.scenarios import CASE_IDS, ScenarioRegistry
from workflow.scenarios.base import (
    ScenarioContext,
    run_case,
    owned_run,
    write_new,
    DEFAULT_CLOCK,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="all")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--business-clock", default=DEFAULT_CLOCK)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--delete-owned-run", type=Path)
    parser.add_argument("--dataset-mode", choices=("test", "demo"))
    args = parser.parse_args(argv)
    try:
        if args.delete_owned_run:
            manifest = owned_run(args.delete_owned_run)
            if args.dataset_mode != manifest["dataset_mode"]:
                raise ValueError("Deletion requires explicit matching --dataset-mode")
            shutil.rmtree(args.delete_owned_run)
            return 0
        if args.output is None or not args.output.is_absolute():
            raise ValueError("--output must be an absolute directory")
        selected = list(CASE_IDS) if args.cases == "all" else args.cases.split(",")
        if not selected or len(set(selected)) != len(selected):
            raise ValueError("Cases must be distinct")
        for case in selected:
            ScenarioRegistry.validate(case)
        clock = datetime.fromisoformat(args.business_clock.replace("Z", "+00:00"))
        if clock.tzinfo is None or clock.utcoffset().total_seconds() != 0:
            raise ValueError("Business clock must be aware UTC")
        if args.resume:
            previous = owned_run(args.resume)
            if selected != [previous["case_id"]]:
                raise ValueError("Resume selects exactly the previous failed case")
            if json.loads((args.resume / "result.json").read_text())["status"] not in {
                "failed",
                "blocked",
            }:
                raise ValueError("Resume requires failed or blocked evidence")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    run_id = f"run-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex}"
    results = []
    for case in selected:
        context = ScenarioContext.isolated(
            args.output,
            case_id=case,
            seed=args.seed,
            clock=clock,
            resume=args.resume,
            run_id=run_id,
        )
        result = run_case(context)
        results.append(asdict(result))
        print(
            json.dumps(
                {
                    "case": case,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "error": result.error,
                    "directory": str(context.directory),
                }
            ),
            flush=True,
        )
    write_new(
        args.output / run_id / "run.json",
        {
            "run_id": run_id,
            "selected": selected,
            "results": results,
            "statuses": {
                case: next(
                    (r["status"] for r in results if r["id"] == case), "not_executed"
                )
                for case in CASE_IDS
            },
            "scope": "isolated mock authority + real business HTTP; browser/production acceptance not executed",
        },
    )
    return 0 if all(r["status"] == "passed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
