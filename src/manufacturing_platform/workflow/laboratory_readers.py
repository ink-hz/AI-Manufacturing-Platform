"""Project-scoped typed laboratory readers with immutable history."""

import json

from . import quality
from .contracts import ObjectDetail, ObjectRelation, ObjectSummary
from .laboratory_models import Calibration, ComponentLink, TestPlan, TestRun
from .orders import _history_rows
from .queries import OBJECT_REGISTRY

TABLES = {
    "test_plan": ("test_plans", TestPlan),
    "test_run": ("test_runs", TestRun),
    "calibration": ("calibrations", Calibration),
    "component_link": ("component_links", ComponentLink),
}


def value_for(kind, row, tx=None, pid=None):
    value = json.loads(row["payload_json"])
    if kind == "test_run" and row["finish_json"]:
        finish = json.loads(row["finish_json"])
        value.update(
            finish=finish,
            **{
                key: finish[key]
                for key in ("state", "outcome", "test_id", "raw", "raw_digest")
            },
        )
    elif kind == "calibration" and row["confirmation_json"]:
        value.update(
            state="confirmed", confirmation=json.loads(row["confirmation_json"])
        )
    elif kind == "component_link":
        value.update(
            state="removed" if row["removal_json"] else "installed",
            removal=json.loads(row["removal_json"]) if row["removal_json"] else None,
        )
    if kind == "component_link" and value.get("source") is not None:
        from .integrations.core_admission import admitted_component_source

        value["source"] = (
            admitted_component_source(tx, pid, row) if tx is not None else None
        )
    return TABLES[kind][1].model_validate(value)


def unit_history(tx, pid, uid):
    return {
        "aliases": [
            json.loads(r["payload_json"])
            for r in tx.execute(
                "SELECT * FROM unit_aliases WHERE project_id=? AND unit_id=? ORDER BY seq",
                (str(pid), str(uid)),
            )
        ],
        "components": [
            value_for("component_link", r, tx, pid).model_dump(exclude={"kind"})
            for r in tx.execute(
                "SELECT * FROM component_links WHERE project_id=? AND unit_id=? ORDER BY seq",
                (str(pid), str(uid)),
            )
        ],
    }


def summary(tx, pid, kind, row):
    value = value_for(kind, row, tx, pid)
    state = value.state
    blockers, actions = [], []
    unit = tx.execute(
        "SELECT sn FROM units WHERE project_id=? AND id=?",
        (str(pid), str(getattr(value, "unit_id", ""))),
    ).fetchone()
    sn = unit["sn"] if unit else ""
    if kind == "test_plan":
        title = f"{value.station} · {value.level} · {value.equipment}"
        actions = ["test_run.start"]
    elif kind == "test_run":
        plan = tx.execute(
            "SELECT payload_json FROM test_plans WHERE project_id=? AND id=?",
            (str(pid), str(value.plan_id)),
        ).fetchone()
        station = json.loads(plan["payload_json"])["station"] if plan else "test"
        title = f"{sn} · {station} · attempt {value.attempt}"
        if value.finish:
            title += f" · {value.raw.origin}"
        if value.state == "running":
            actions = ["test_run.finish"]
        elif value.state in {"aborted", "invalid"}:
            blockers = [f"Run {value.state}: {value.finish.evidence}"]
        elif value.outcome == "fail":
            state = "fail"
            blockers = ["Run measurements failed; qualified rework is required"]
        else:
            state = "pass"
            if quality.complete_pass(
                tx,
                pid,
                value.test_id,
                value.unit_id,
                value.revision_id,
                scope=value.scope,
            ):
                actions = ["calibration.record"]
            else:
                blockers = ["Historical passing run lacks current qualified evidence"]
    elif kind == "calibration":
        title = f"{sn} · {value.algorithm_version} · {value.origin}"
        if value.state == "pending":
            blockers = ["Separate matching readback confirmation is pending"]
            actions = ["calibration.confirm"]
    else:
        title = (
            f"{sn} · {value.material_id} · {value.component_serial} · {value.origin}"
        )
        if value.state == "installed":
            actions = ["component.remove"]
    return ObjectSummary(
        id=row["id"],
        project_id=pid,
        kind=kind,
        title=title,
        state=state,
        version=1,
        blocking_reasons=blockers,
        next_actions=actions,
    )


def register(kind, table, model):
    def count(tx, pid):
        return tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(pid),)
        ).fetchone()[0]

    def page(tx, pid, limit, offset):
        return [
            summary(tx, pid, kind, r)
            for r in tx.execute(
                f"SELECT * FROM {table} WHERE project_id=? ORDER BY seq LIMIT ? OFFSET ?",
                (str(pid), limit, offset),
            )
        ]

    def detail(tx, pid, ident):
        row = tx.execute(
            f"SELECT * FROM {table} WHERE project_id=? AND id=?", (str(pid), str(ident))
        ).fetchone()
        if not row:
            return None
        value = value_for(kind, row, tx, pid)
        relations = []
        for field, target in [
            ("unit_id", "unit"),
            ("plan_id", "test_plan"),
            ("run_id", "test_run"),
            ("revision_id", "revision"),
            ("test_id", "test"),
        ]:
            if getattr(value, field, None):
                relations.append(
                    ObjectRelation(
                        relation=target,
                        project_id=pid,
                        kind=target,
                        id=getattr(value, field),
                    )
                )
        return ObjectDetail[model](
            summary=summary(tx, pid, kind, row),
            value=value,
            relations=relations,
            evidence=[],
            history=_history_rows(
                tx.execute(
                    "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id LIMIT 500",
                    (str(pid), str(ident)),
                ).fetchall()
            ),
        )

    OBJECT_REGISTRY.register(kind, model, count=count, summaries=page, detail=detail)


for kind, (table, model) in TABLES.items():
    register(kind, table, model)
