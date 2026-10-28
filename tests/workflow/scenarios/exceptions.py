"""Original exceptional business scenarios; expected rejections are explicit steps."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, UTC
import hashlib

from .base import ROOT, ScenarioBlocked
from .fixtures import connect


def e30(context):
    context.expected.update(
        actual_react=True,
        two_editors=True,
        cas_conflict=True,
        draft_retained=True,
        whole_handbook=True,
        departures=1,
    )
    release = context.directory / "ui-release"
    (release / "docs").mkdir(parents=True)
    path = release / "docs/manufacturing-system-handbook.md"
    shutil.copyfile(ROOT / "docs/manufacturing-system-handbook.md", path)
    (release / "handbook-metadata.json").write_text(
        json.dumps(
            {
                "files": {
                    "docs/manufacturing-system-handbook.md": {
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                }
            }
        )
    )
    (release / "webui/dist").mkdir(parents=True)
    context.ui_assets = str(release / "webui/dist")
    api = connect(context)
    pid = api.project("2")
    api.grant(pid, "planner", ["project_owner", "planner"])
    command = (
        json.loads(os.environ["WORKFLOW_E30_COMMAND"])
        if os.environ.get("WORKFLOW_E30_COMMAND")
        else [
            shutil.which("node") or "node",
            str(ROOT / "webui/node_modules/vitest/vitest.mjs"),
        ]
    )
    if not shutil.which(command[0]) and not Path(command[0]).is_file():
        raise ScenarioBlocked(
            "E30 private pinned Node runtime unavailable; actual React evidence required"
        )
    args = [
        *command,
        "run",
        "src/workflow/acceptanceNavigationHttp.test.tsx",
        "--configLoader",
        "runner",
        "--reporter=json",
        "--outputFile=" + str(context.directory / "e30-vitest.json"),
    ]
    context.evidence.record(
        "ui-runtime",
        {
            "command": args,
            "node_binary_sha256": hashlib.sha256(
                Path(shutil.which(command[0]) or command[0]).resolve().read_bytes()
            ).hexdigest(),
            "node_version": subprocess.check_output(
                [command[0], "--version"], text=True
            ).strip(),
            "package_lock_sha256": hashlib.sha256(
                (ROOT / "webui/package-lock.json").read_bytes()
            ).hexdigest(),
            "boundary": "private ReactDOM/jsdom against actual loopback business HTTP; no browser automation",
        },
    )
    env = {
        **os.environ,
        "WORKFLOW_HTTP_BASE": api.base,
        "WORKFLOW_HTTP_SECRET": api.secret,
        "WORKFLOW_PROJECT_ID": pid,
        "WORKFLOW_SEED": str(context.seed),
        "WORKFLOW_E30_EVIDENCE": str(context.directory / "e30-react-evidence.json"),
    }
    process = subprocess.run(
        args, cwd=ROOT / "webui", env=env, capture_output=True, text=True, timeout=60
    )
    context.evidence.record(
        "ui-process",
        {
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        },
    )
    assert process.returncode == 0, (
        "Actual E30 React/HTTP test failed; inspect ui-process artifact"
    )
    evidence = json.loads((context.directory / "e30-react-evidence.json").read_text())
    assert len(evidence["assertions"]) == 6 and evidence["events"].count("leave") == 1
    context.actual.update(context.expected, handbook_sha256=evidence["handbook_sha256"])


# The same named callables are shared by pytest wrappers, CLI and private image candidate.
from .orders_supply_cases import e01 as e01
from .orders_supply_cases import e02 as e02
from .orders_supply_cases import e03 as e03
from .orders_supply_cases import e04 as e04
from .orders_supply_cases import e05 as e05
from .orders_supply_cases import e06 as e06
from .orders_supply_cases import e07 as e07
from .orders_supply_cases import e08 as e08
from .orders_supply_cases import e09 as e09
from .orders_supply_cases import e10 as e10
from .execution_quality_cases import e11 as e11
from .execution_quality_cases import e12 as e12
from .execution_quality_cases import e13 as e13
from .execution_quality_cases import e14 as e14
from .execution_quality_cases import e15 as e15
from .execution_quality_cases import e16 as e16
from .execution_quality_cases import e17 as e17
from .execution_quality_cases import e18 as e18
from .execution_quality_cases import e19 as e19
from .delivery_recovery_cases import e20 as e20
from .delivery_recovery_cases import e21 as e21
from .delivery_recovery_cases import e22 as e22
from .delivery_recovery_cases import e23 as e23
from .delivery_recovery_cases import e24 as e24
from .delivery_recovery_cases import e25 as e25
from .delivery_recovery_cases import e26 as e26
from .delivery_recovery_cases import e27 as e27
from .delivery_recovery_cases import e28 as e28
from .delivery_recovery_cases import e29 as e29
from .delivery_recovery_cases import e31 as e31
from .delivery_recovery_cases import e32 as e32
