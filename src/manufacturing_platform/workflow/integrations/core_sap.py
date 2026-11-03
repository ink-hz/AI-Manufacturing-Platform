"""SAP owns commercial/planning facts and accounting, never physical stock."""

from .core_guards import require
from .core_systems import CoreSystem


class SapSystem(CoreSystem):
    def make_fact(self, project_id, payload, external_id, *, causes=(), now=None):
        now = now or self.store.clock()
        if payload["fact_type"] in {
            "sap.accounting_entry",
            "sap.completion_posting",
            "sap.receipt_posting",
            "sap.shipment_posting",
            "sap.variance_posting",
        }:
            payload = dict(payload, posted_at=now)
        return super().make_fact(
            project_id, payload, external_id, causes=causes, now=now
        )

    def prepare(self, operation, observations):
        from uuid import uuid5, NAMESPACE_URL
        from .core_projections import domain_id
        from ..orders import own

        p = operation.payload
        if p.operation == "sap.request_bom":
            from .bom_sync import request_fact

            return [request_fact(self, operation, observations)]
        facts = super().prepare(operation, observations)
        if p.operation == "sap.release_work_order":
            revision = observations.fact(p.released_revision)
            require(
                revision.payload.fact_type == "pdm.revision",
                "Released PDM engineering required",
            )
            with self.registry.workflow_store.transaction() as tx:
                project = tx.execute(
                    "SELECT * FROM projects WHERE id=?", (str(operation.project_id),)
                ).fetchone()
            facts[0] = facts[0].model_copy(update={"caused_by": [revision.source_key]})
            payload = dict(
                fact_type="sap.bom_request",
                work_order_id=domain_id(facts[0]),
                product=project["product"],
                material_ids=[m.material_id for m in revision.payload.bom_materials],
                requested_revision=revision.payload.revision,
            )
            facts.append(
                self.make_fact(
                    operation.project_id,
                    payload,
                    uuid5(NAMESPACE_URL, f"{operation.operation_id}:bom"),
                    causes=[facts[0].source_key, revision.source_key],
                )
            )
        elif p.operation == "sap.publish_plan":
            from .bom_sync import plan_causes

            facts[0] = facts[0].model_copy(
                update={"caused_by": plan_causes(self, operation, observations)}
            )
            with self.registry.workflow_store.transaction() as tx:
                for req in p.requirements:
                    wo = own(tx, "work_orders", operation.project_id, req.work_order_id)
                    order = own(
                        tx, "order_lines", operation.project_id, wo["order_line_id"]
                    )
                    payload = req.model_dump(mode="json")
                    payload.update(
                        fact_type="sap.purchase_requirement",
                        due_date=order["current_due"],
                    )
                    facts.append(
                        self.make_fact(
                            operation.project_id,
                            payload,
                            uuid5(
                                NAMESPACE_URL,
                                f"{operation.operation_id}:purchase:{req.requirement_id}",
                            ),
                            causes=[facts[0].source_key],
                        )
                    )
        return facts

    def transition(self, tx, operation, facts, observations):
        p = operation.payload
        if p.operation == "sap.release_work_order":
            observations.fact(p.released_revision)
        elif p.operation == "sap.post_movement":
            cause = observations.fact(p.cause)
            require(
                cause.payload.fact_type in {"wms.pick", "wms.return"},
                "Exact physical movement required",
            )
            require(p.account == "raw-custody", "Physical movement account mismatch")
            require(
                p.allocations == cause.payload.allocations,
                "Accounting allocations differ from physical cause",
            )
            require(
                not any(
                    f.payload.cause == p.cause and f.payload.account == p.account
                    for f in observations.of_type("sap.accounting_entry")
                ),
                "Physical cause already posted",
            )
        elif p.operation == "sap.post_completion":
            require(p.account == "production-completed", "Completion account mismatch")
            completion = observations.fact(p.completion)
            require(
                completion.payload.fact_type == "mes.completion"
                and completion.payload.work_order_id == p.work_order_id,
                "Completion posting scope mismatch",
            )
            require(
                not any(
                    f.payload.completion == p.completion
                    and f.payload.account == p.account
                    for f in observations.of_type("sap.completion_posting")
                ),
                "Completion already posted",
            )
        elif p.operation not in {
            "sap.release_order",
            "sap.publish_plan",
            "sap.request_bom",
        }:
            require(False, "SAP operation prerequisite unavailable")

    def consume_fact(self, tx, delivery, observations):
        f, p = delivery.fact, delivery.fact.payload
        if p.fact_type == "wms.stocktake":
            payload = p.model_dump(mode="json")
            payload.update(
                fact_type="sap.variance_posting",
                cause=f.source_key,
                account="raw-variance",
            )
        elif p.fact_type == "wms.receipt":
            payload = dict(
                fact_type="sap.receipt_posting",
                cause=f.source_key.model_dump(),
                material_lot_id=p.material_lot_id,
                material_id=p.material_id,
                owner_id=p.owner_id,
                amount=p.amount.model_dump(mode="json"),
                account="raw-received",
            )
        elif p.fact_type == "mes.completion":
            if any(
                v.payload.completion == f.source_key
                and v.payload.account == "production-completed"
                for v in observations.of_type("sap.completion_posting")
            ):
                return
            self.emit(
                tx,
                self.child(
                    delivery,
                    dict(
                        fact_type="sap.completion_posting",
                        completion=f.source_key,
                        work_order_id=p.work_order_id,
                        account="production-completed",
                        evidence="Exact completed unit reconciliation",
                    ),
                ),
            )
            return
        elif p.fact_type == "mes.execution" and p.material_uses:
            payload = dict(
                fact_type="sap.accounting_entry",
                cause=f.source_key,
                account="raw-consumed",
                allocations=[a.model_dump(mode="json") for a in p.material_uses],
                evidence="Exact consumed line-side material",
            )
        elif p.fact_type == "wms.shipment":
            payload = dict(
                fact_type="sap.shipment_posting",
                cause=f.source_key.model_dump(),
                shipment_id=p.shipment_id,
                order_line_id=p.order_line_id,
                units=[u.model_dump(mode="json") for u in p.units],
                amount=p.amount.model_dump(mode="json"),
                account="finished-shipped",
            )
        elif p.fact_type in {"wms.pick", "wms.return"}:
            payload = dict(
                fact_type="sap.accounting_entry",
                cause=f.source_key.model_dump(),
                account="raw-custody",
                allocations=[a.model_dump(mode="json") for a in p.allocations],
                evidence=p.evidence,
            )
        else:
            return
        existing = [
            v
            for v in observations.facts.values()
            if v.source.system == "sap"
            and getattr(v.payload, "cause", None) == f.source_key
            and getattr(v.payload, "account", None) == payload["account"]
        ]
        if not existing:
            self.emit(tx, self.child(delivery, payload))
