"""Bounded, project-scoped traversal of actual typed genealogy."""

from uuid import UUID

from .contracts import DomainError
from .execution_models import sn_key
from .feedback_models import TraceEdge, TraceNode, TraceResult
from .orders import own, project

ADMITTED = """JOIN execution_events e ON e.id=c.execution_event_id AND e.project_id=c.project_id AND e.unit_id=c.unit_id JOIN execution_admissions a ON a.event_id=e.id AND a.project_id=e.project_id AND a.admitted=1 WHERE c.project_id=? AND e.status='accepted'"""


def query(
    tx,
    project_id,
    *,
    sn: str | None = None,
    material_lot_id: UUID | None = None,
    limit=500,
) -> TraceResult:
    if (
        (sn is None) == (material_lot_id is None)
        or not 1 <= limit <= 500
        or (sn is not None and (not sn_key(sn) or len(sn) > 200))
    ):
        raise DomainError(
            "INVALID_TRACE", 422, "Choose exactly one bounded SN or material lot"
        )
    pid = str(project_id)
    nodes = {}
    edges = {}
    truncated = False

    def add(kind, ident, title, customer=None):
        nonlocal truncated
        if (kind, ident) in nodes:
            return True
        if len(nodes) >= limit:
            truncated = True
            return False
        nodes[(kind, ident)] = TraceNode(
            id=ident,
            kind=kind,
            project_id=project_id,
            title=title,
            customer_id=customer,
        )
        return True

    def edge(source_kind, source, target_kind, target, relation):
        if (source_kind, source) in nodes and (target_kind, target) in nodes:
            edges[(source_kind, source, target_kind, target, relation)] = TraceEdge(
                source_kind=source_kind,
                source_id=source,
                target_kind=target_kind,
                target_id=target,
                relation=relation,
            )

    def rows(sql, args):
        nonlocal truncated
        # Every fan-out is SQL bounded before materialization, including evidence.
        budget = limit  # Deduplicated existing nodes still need their physical edges.
        found = tx.execute(sql + " LIMIT ?", (*args, budget + 1)).fetchall()
        if len(found) > budget:
            truncated = True
        return found[:budget]

    if sn is not None:
        unit = tx.execute(
            "SELECT * FROM units WHERE project_id=? AND sn_key=? LIMIT 1",
            (pid, sn_key(sn)),
        ).fetchone()
        if not unit:
            raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
        units = [unit]
    else:
        lot = own(tx, "material_lots", project_id, material_lot_id)
        add("material_lot", lot["id"], lot["lot_id"])
        units = rows(
            "SELECT DISTINCT u.* FROM material_consumption c "
            + ADMITTED.replace(
                " WHERE",
                " JOIN units u ON u.id=c.unit_id AND u.project_id=c.project_id WHERE",
            )
            + " AND c.lot_id=? ORDER BY u.registered_seq",
            (pid, str(material_lot_id)),
        )
    for unit in units:
        if not add("unit", unit["id"], unit["sn"]):
            break
        if material_lot_id:
            edge("material_lot", str(material_lot_id), "unit", unit["id"], "consumed")
        wo = own(tx, "effective_work_orders", project_id, unit["work_order_id"])
        revision = own(tx, "engineering_revisions", project_id, unit["revision_id"])
        order = own(tx, "order_lines", project_id, wo["order_line_id"])
        add("work_order", wo["id"], "Work order " + wo["id"][:8])
        add("revision", revision["id"], revision["internal_revision"])
        add(
            "order_line",
            order["id"],
            "Order " + order["id"][:8],
            project(tx, project_id)["customer_id"],
        )
        edge("unit", unit["id"], "work_order", wo["id"], "work_order")
        edge("unit", unit["id"], "revision", revision["id"], "revision")
        edge("work_order", wo["id"], "order_line", order["id"], "order")
        for lot in rows(
            "SELECT DISTINCT l.id,l.lot_id FROM material_consumption c "
            + ADMITTED.replace(
                " WHERE",
                " JOIN material_lots l ON l.id=c.lot_id AND l.project_id=c.project_id WHERE",
            )
            + " AND c.unit_id=? ORDER BY l.id",
            (pid, unit["id"]),
        ):
            add("material_lot", lot["id"], lot["lot_id"])
            edge("material_lot", lot["id"], "unit", unit["id"], "consumed")
        tests = rows(
            "SELECT t.*,b.prior_test_id FROM quality_tests t LEFT JOIN quality_test_bases b ON b.test_id=t.id AND b.project_id=t.project_id WHERE t.project_id=? AND t.unit_id=? ORDER BY t.seq",
            (pid, unit["id"]),
        )
        for test in tests:
            add("test", test["id"], f"Test {test['attempt']} · {test['outcome']}")
            edge("unit", unit["id"], "test", test["id"], "test")
            if test["prior_test_id"]:
                edge("test", test["prior_test_id"], "test", test["id"], "prior_test")
        for rw in rows(
            "SELECT * FROM rework_orders WHERE project_id=? AND unit_id=? ORDER BY seq",
            (pid, unit["id"]),
        ):
            add("rework", rw["id"], rw["route_id"])
            edge("unit", unit["id"], "rework", rw["id"], "rework")
            for test in tests:
                if test["rework_order_id"] == rw["id"]:
                    edge("rework", rw["id"], "test", test["id"], "test")
        for release in rows(
            "SELECT r.* FROM quality_releases r JOIN quality_release_units u ON u.release_id=r.id AND u.project_id=r.project_id WHERE u.project_id=? AND u.unit_id=? ORDER BY r.seq",
            (pid, unit["id"]),
        ):
            add("release", release["id"], release["kind"] + " · " + release["decision"])
            edge("unit", unit["id"], "release", release["id"], "release")
        for shipped in rows(
            "SELECT * FROM shipment_items WHERE project_id=? AND unit_id=? ORDER BY shipment_id",
            (pid, unit["id"]),
        ):
            add(
                "shipment",
                shipped["shipment_id"],
                "Shipment " + shipped["shipment_id"][:8],
            )
            edge("unit", unit["id"], "shipment", shipped["shipment_id"], "shipment")
            edge(
                "shipment",
                shipped["shipment_id"],
                "order_line",
                shipped["order_line_id"],
                "order",
            )
        for rma in rows(
            "SELECT * FROM rmas WHERE project_id=? AND unit_id=? ORDER BY seq",
            (pid, unit["id"]),
        ):
            add("rma", rma["id"], "RMA " + rma["id"][:8])
            edge("shipment", rma["shipment_id"], "rma", rma["id"], "rma")
            for capa in rows(
                "SELECT * FROM capas WHERE project_id=? AND rma_id=? ORDER BY seq",
                (pid, rma["id"]),
            ):
                add("capa", capa["id"], "CAPA · " + capa["state"])
                edge("rma", rma["id"], "capa", capa["id"], "capa")
    return TraceResult(
        nodes=list(nodes.values()), edges=list(edges.values()), truncated=truncated
    )
