"""Verification conclusions use current durable references, never quantity proof."""
from .contracts import DomainError
from .material_task_reference_models import ArrivalTaskReference, TaskReferenceEvidence
from .material_task_references import resolve_reference, reference_status
from .quality import fail

OUTCOMES = {'identity_verified', 'unable_to_verify', 'incorrect_observation', 'superseded'}


def close_evidence(tx, pid, row, command):
    if command.outcome not in OUTCOMES or command.handoff_ids:
        fail('Verification requires an identity conclusion without quantity evidence', 422)
    if command.outcome != 'identity_verified':
        if command.resolved_reference is not None:
            fail('Only identity verification accepts a resolved reference', 422)
        return {}
    pinned = TaskReferenceEvidence.model_validate_json(row['reference_json'])
    current, current_ref, issue = reference_status(tx, pid, pinned)
    if not current and command.resolved_reference is None:
        raise DomainError('REFERENCE_STALE', 409, 'Explicit current reference required to verify identity')
    resolved = resolve_reference(tx, pid, command.resolved_reference or pinned.reference)
    if resolved.scope_key != pinned.scope_key:
        # An arrival can resolve to its currently matched, existing exact receipt.
        # Native components cannot become receipts solely through material identity.
        if not isinstance(pinned.reference, ArrivalTaskReference) or current_ref is None:
            fail('Resolved reference belongs to another scope', 422)
        arrival = resolve_reference(tx, pid, current_ref)
        if resolved.reference.kind not in ('receipt', 'source_receipt') or arrival.receipt_id != resolved.receipt_id:
            fail('Resolved receipt is not the current arrival match', 422)
    return dict(resolved_reference=resolved.reference.model_dump(mode='json'),
                resolved_evidence=resolved.model_dump(mode='json', exclude={'requirement_id', 'task_kinds'}))
