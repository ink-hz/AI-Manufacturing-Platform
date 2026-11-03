"""Fixed evidence systems; independent PLC observations and owned test originals."""

from .core_systems import CoreSystem, authorize
from .core_guards import require
from .evidence_projections import project_fact, validate_fact


class EvidenceSystem(CoreSystem):
    def __init__(self, system, store, registry):
        require(
            system == store.system
            and system in {"product_test", "plc", "customer", "overseas", "bi"},
            "Evidence store identity mismatch",
        )
        super().__init__(store, registry)

    validate_fact = staticmethod(validate_fact)

    def prepare(self, operation, observations):
        from . import test_artifacts

        p = operation.payload
        if p.operation == "bi.refresh":
            from .bi_metrics import snapshot

            return [snapshot(self, operation, observations)]
        if p.operation == "product_test.prepare_artifact":
            return [test_artifacts.prepare(self, operation, observations)]
        if p.operation == "plc.readback":
            from ..laboratory import digest, parameter_content

            write = observations.fact(p.calibration)
            require(
                write.payload.fact_type == "product_test.calibration",
                "Actual calibration write required",
            )
            require(
                not any(
                    previous.payload.source_identity == p.source_identity
                    for previous in observations.of_type("plc.readback")
                ),
                "PLC observation source identity already committed",
            )
            observed = digest(parameter_content(p.parameters))
            matches = observed == digest(parameter_content(write.payload.parameters))
            facts = [
                self.make_fact(
                    operation.project_id,
                    dict(
                        fact_type="plc.readback",
                        parameter_digest=observed,
                        confirmation_matches=matches,
                        **p.model_dump(mode="json", exclude={"operation"}),
                    ),
                    operation.operation_id,
                )
            ]
        else:
            facts = super().prepare(operation, observations)
        causes = []
        if p.operation in {"product_test.run", "product_test.calibrate"}:
            test_artifacts.validate_inline(self.store, operation.project_id, p)
            originals = [
                f
                for f in observations.of_type("product_test.artifact")
                if f.payload.prepared.artifact_ref == p.artifact_ref
            ]
            require(len(originals) == 1, "Exact original preparation source required")
            causes.append(originals[0].source_key)
        if p.operation == "product_test.run":
            request = observations.fact(p.request)
            q = request.payload
            require(
                q.fact_type == "mes.test_request"
                and (
                    q.work_order_id,
                    q.unit_id,
                    q.revision_id,
                    q.plan_id,
                    q.program_version,
                    q.firmware_version,
                )
                == (
                    p.work_order_id,
                    p.unit_id,
                    p.revision_id,
                    p.plan_id,
                    p.program_version,
                    p.firmware_version,
                ),
                "Test differs from exact MES request",
            )
            causes.append(p.request)
            facts[0] = facts[0].model_copy(
                update={
                    "source": facts[0].source.model_copy(
                        update={"occurred_at": p.occurred_at}
                    )
                }
            )
        if p.operation in {"customer.approve_revision", "customer.map_serial"}:
            key = (
                p.revision if p.operation == "customer.approve_revision" else p.shipment
            )
            observations.fact(key)
            causes.append(key)
        if p.operation == "plc.readback":
            write = observations.fact(p.calibration)
            require(
                write.payload.fact_type == "product_test.calibration",
                "Actual product-test write required",
            )
            causes.append(p.calibration)
        if p.operation in {
            "product_test.run",
            "product_test.calibrate",
            "plc.readback",
        }:
            from .core_eligibility import current_start, validate_eligibility

            starts = [
                f
                for f in observations.of_type("mes.start")
                if any(u.unit_id == p.unit_id for u in f.payload.units)
            ]
            require(bool(starts), "Current physical start required")
            current = current_start(
                operation, starts[-1], observations, self.store.clock()
            )
            causes.extend(
                validate_eligibility(current, observations, self.store.clock())
            )
        if p.operation == "plc.set_state":
            request = observations.fact(p.process_request)
            q = request.payload
            require(
                q.fact_type == "mes.process_request"
                and (q.equipment, q.program_version)
                == (p.equipment, p.program_version),
                "PLC equipment differs from actual MES process request",
            )
            require(
                request.source.occurred_at <= p.observed_at <= self.store.clock(),
                "PLC observation time mismatch",
            )
            causes.append(p.process_request)
        if p.operation == "plc.sample":
            session = observations.fact(p.mes_session)
            require(
                session.payload.fact_type == "mes.start"
                and session.payload.work_order_id == p.work_order_id
                and any(u.unit_id == p.unit_id for u in session.payload.units),
                "PLC sample session scope mismatch",
            )
            equipment = observations.fact(session.payload.equipment)
            require(
                (equipment.payload.equipment, equipment.payload.program_version)
                == (p.equipment, p.program_version),
                "PLC sample equipment/program mismatch",
            )
            causes.append(p.mes_session)
        if p.operation in {
            "overseas.report_return",
            "overseas.receive_shipment",
            "customer.confirm_delivery",
            "customer.receive_shipment",
        }:
            from .external_claims import prepare_causes

            causes.extend(prepare_causes(p, observations))
        return [f.model_copy(update={"caused_by": causes}) for f in facts]

    def transition(self, tx, operation, facts, observations):
        if operation.payload.operation == "product_test.prepare_artifact":
            from .test_artifacts import persist

            persist(tx, facts[0])


def register_evidence(registry):
    for system in ("product_test", "plc", "customer", "overseas", "bi"):
        registry.register(
            system,
            factory=lambda store, system=system: EvidenceSystem(
                system, store, registry
            ),
            projector=project_fact,
            authorize=authorize,
        )
