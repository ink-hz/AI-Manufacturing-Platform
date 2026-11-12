"""Resolve only durable project-local observations, without source I/O."""
import json
from uuid import UUID
from .arrival import match_count
from .authorization import effective_permissions, require_project
from .clock import business_time
from .contracts import DomainError
from .material_task_reference_models import (ArrivalTaskReference, MesComponentTaskReference,
    ReceiptTaskReference, SourceReceiptTaskReference, ResolvedTaskReference)
from .orders import own
from .quantity_provenance import source_from_ref


def _scope(*parts):
    return json.dumps(parts, ensure_ascii=False, separators=(',', ':'))


def _provenance(source, pid, kind, ident):
    p = source_from_ref(source, reference=str(ident), project_id=str(pid), object_kind=kind,
                        object_id=str(ident), value=None, unit=None, meaning='observation')
    return dict(origin=p.origin, environment=p.environment, system=p.system, source_type=p.source_type,
                external_id=p.external_id, version=p.version, namespace=p.namespace,
                occurred_at=p.occurred_at, collected_at=p.collected_at)


def _receipt(tx, pid, ident):
    row = own(tx, 'supply_receipts', pid, ident)
    commitment = own(tx, 'supply_commitments', pid, row['commitment_id'])
    req = own(tx, 'requirements', pid, commitment['requirement_id'])
    lot = own(tx, 'material_lots', pid, row['material_lot_id'])
    return row, req, lot


def resolve_reference(tx, project_id, reference, *, require_current=True):
    pid = UUID(str(project_id))
    if isinstance(reference, ArrivalTaskReference):
        row = own(tx, 'arrivals', pid, reference.id)
        version = 1 + match_count(tx, pid, reference.id)
        if reference.version > version or (require_current and reference.version != version):
            raise DomainError('REFERENCE_STALE', 409, 'Arrival match changed')
        match = tx.execute('SELECT receipt_id FROM arrival_matches WHERE project_id=? AND arrival_id=? ORDER BY seq LIMIT 1 OFFSET ?',
                           (str(pid), str(reference.id), reference.version - 2)).fetchone() if reference.version > 1 else None
        payload = json.loads(row['payload_json'])
        return ResolvedTaskReference(reference=reference, scope_key=_scope('arrival', str(reference.id)),
            title=payload['arrival_number'], **_provenance(payload['source'], pid, 'arrival', reference.id),
            receipt_id=match[0] if match else None, task_kinds=['verify'])
    if isinstance(reference, MesComponentTaskReference):
        row = tx.execute('''SELECT b.*, s.id snapshot_id, s.collected_at, c.component_key, c.material_id, c.unit
            FROM mes_order_bindings b JOIN mes_material_snapshots s ON s.binding_id=b.id
            JOIN mes_material_components c ON c.snapshot_id=s.id
            WHERE b.project_id=? AND b.id=? AND s.id=? AND c.component_key=?''',
            (str(pid), str(reference.binding_id), str(reference.snapshot_id), reference.component_key)).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', 404, 'Component observation not found')
        latest = tx.execute('SELECT id FROM mes_material_snapshots WHERE binding_id=? ORDER BY rowid DESC LIMIT 1', (row['id'],)).fetchone()
        if require_current and (not row['active'] or latest['id'] != row['snapshot_id']):
            raise DomainError('REFERENCE_STALE', 409, 'MES observation changed')
        return ResolvedTaskReference(reference=reference, scope_key=_scope('mes_component', row['id'], row['component_key']),
            title=row['material_id'], origin='native', environment=row['environment'] if row['environment'] in ('production','test','development','mock') else 'unknown',
            system='mes', source_type='order_component', external_id=row['shop_order'], version=row['snapshot_id'], namespace=row['namespace'],
            collected_at=row['collected_at'], work_order_id=row['work_order_id'], material_id=row['material_id'], unit=row['unit'], task_kinds=['verify'])
    if isinstance(reference, SourceReceiptTaskReference):
        from .integrations.enterprise_admission import projected_fact
        from .integrations.contracts import ProjectionResult
        from .integrations.store import identity
        fact = projected_fact(tx, pid, reference.source_key)
        if fact.payload.fact_type != 'wms.receipt':
            raise DomainError('NOT_FOUND', 404, 'Source receipt not found')
        projection = tx.execute('SELECT result_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?', identity(pid, reference.source_key)).fetchone()
        result = ProjectionResult.model_validate_json(projection[0])
        targets = [target.id for target in result.targets if target.kind == 'receipt']
        if len(targets) != 1:
            raise DomainError('SOURCE_CONFLICT', 409, 'Source receipt target is ambiguous')
        receipt, req, lot = _receipt(tx, pid, targets[0])
        if (str(fact.payload.commitment_id) != receipt['commitment_id'] or str(fact.payload.material_lot_id) != receipt['material_lot_id'] or
                fact.source.system != receipt['source_system'] or fact.source.object_type != receipt['source_type'] or
                fact.source.external_id != receipt['source_external_id'] or fact.source.version != receipt['source_version']):
            raise DomainError('SOURCE_CONFLICT', 409, 'Source receipt identity mismatch')
        source = fact.source.model_dump()
    elif isinstance(reference, ReceiptTaskReference):
        receipt, req, lot = _receipt(tx, pid, reference.id)
        source = json.loads(receipt['source_json'])
    else:
        raise TypeError('Unsupported task reference')
    return ResolvedTaskReference(reference=reference, scope_key=_scope('receipt', receipt['id']), title=lot['material_id'],
        **_provenance(source, pid, 'receipt', receipt['id']), work_order_id=req['work_order_id'], material_id=lot['material_id'],
        material_lot_id=lot['id'], receipt_id=receipt['id'], unit=receipt['unit'], requirement_id=req['id'], task_kinds=['verify','iqc'])


def reference_status(tx, project_id, evidence):
    ref = evidence.reference
    try:
        resolve_reference(tx, project_id, ref)
        return True, ref, None
    except DomainError:
        if isinstance(ref, ArrivalTaskReference):
            row = tx.execute('SELECT 1 FROM arrivals WHERE id=? AND project_id=?', (str(ref.id), str(project_id))).fetchone()
            if row:
                current = ArrivalTaskReference(kind='arrival', id=ref.id, version=1 + match_count(tx, project_id, ref.id))
                return False, current, 'Arrival match changed'
        if isinstance(ref, MesComponentTaskReference):
            row = tx.execute('''SELECT s.id FROM mes_order_bindings b JOIN mes_material_snapshots s ON s.binding_id=b.id
                JOIN mes_material_components c ON c.snapshot_id=s.id AND c.component_key=? WHERE b.id=? AND b.project_id=? AND b.active=1
                AND s.id=(SELECT id FROM mes_material_snapshots WHERE binding_id=b.id ORDER BY rowid DESC LIMIT 1)''',
                (ref.component_key, str(ref.binding_id), str(project_id))).fetchone()
            if row:
                return False, ref.model_copy(update={'snapshot_id': UUID(row[0])}), 'MES observation changed'
        return False, None, 'Reference unavailable or changed'


def reference_page(service, actor, project_id, *, task_kind='verify', kind='all',
                   work_order_id=None, requirement_id=None, search='', limit=50, offset=0):
    service._pagination(limit, offset)
    if task_kind not in ('verify','iqc') or kind not in ('all','arrival','mes_component','receipt','source_receipt'):
        raise DomainError('INVALID_COMMAND', 422, 'Unknown reference kind')
    with service.store.transaction() as tx:
        project = require_project(tx, actor, project_id)
        pid = UUID(str(project_id))
        if work_order_id is not None:
            own(tx, 'work_orders', pid, work_order_id)
        if requirement_id is not None:
            req = own(tx, 'requirements', pid, requirement_id)
            if work_order_id is not None and req['work_order_id'] != str(work_order_id):
                raise DomainError('NOT_FOUND', 404, 'Requirement not found in work order')
        candidates = []
        if kind in ('all', 'arrival') and task_kind == 'verify':
            for row in tx.execute('SELECT id FROM arrivals WHERE project_id=? ORDER BY seq', (str(pid),)):
                candidates.append(ArrivalTaskReference(kind='arrival', id=row['id'], version=1 + match_count(tx, pid, row['id'])))
        if kind in ('all', 'mes_component') and task_kind == 'verify':
            for row in tx.execute('''SELECT b.id binding_id,s.id snapshot_id,c.component_key FROM mes_order_bindings b
                JOIN mes_material_snapshots s ON s.binding_id=b.id AND s.id=(SELECT id FROM mes_material_snapshots WHERE binding_id=b.id ORDER BY rowid DESC LIMIT 1)
                JOIN mes_material_components c ON c.snapshot_id=s.id WHERE b.project_id=? AND b.active=1 ORDER BY b.rowid,c.position''', (str(pid),)):
                candidates.append(MesComponentTaskReference(kind='mes_component', **dict(row)))
        if kind in ('all', 'source_receipt'):
            from .integrations.core_models import SourceKey
            for row in tx.execute("SELECT system,object_type,external_id,version FROM integration_projections WHERE project_id=? AND system='wms' AND object_type='receipt' ORDER BY rowid", (str(pid),)):
                candidates.append(SourceReceiptTaskReference(kind='source_receipt', source_key=SourceKey(**dict(row))))
        if kind in ('all', 'receipt'):
            for row in tx.execute('SELECT id FROM supply_receipts WHERE project_id=? ORDER BY rowid', (str(pid),)):
                candidates.append(ReceiptTaskReference(kind='receipt', id=row['id']))
        items, scopes = [], set()
        roles = effective_permissions(tx, actor, pid).roles
        from .material_handoffs import applicable
        can_open = bool(not actor.read_only and roles & {'supply','project_owner'} and applicable(tx, pid))
        for ref in candidates:
            resolved = resolve_reference(tx, pid, ref)
            if task_kind not in resolved.task_kinds:
                continue
            context_work_order = work_order_id or (UUID(req['work_order_id']) if requirement_id else None)
            if isinstance(ref, ArrivalTaskReference):
                # Arrival is a project observation, not evidence of order ownership.
                pass
            elif isinstance(ref, MesComponentTaskReference):
                if context_work_order and resolved.work_order_id != context_work_order:
                    continue
            else:
                if work_order_id and resolved.work_order_id != work_order_id:
                    continue
                if requirement_id:
                    receipt, prior, lot = _receipt(tx, pid, resolved.receipt_id)
                    if (any(prior[field] != req[field] for field in ('lineage_id', 'work_order_id', 'material_id', 'owner_id', 'unit', 'scale'))
                            or any(lot[field] != req[field] for field in ('material_id', 'owner_id', 'unit', 'scale'))
                            or receipt['unit'] != req['unit']):
                        continue
            if search.strip() and search.strip().casefold() not in ' '.join(str(v or '') for v in (resolved.title, resolved.material_id, resolved.external_id)).casefold():
                continue
            if resolved.scope_key in scopes:
                continue
            scopes.add(resolved.scope_key)
            existing = tx.execute("SELECT id FROM material_tasks WHERE project_id=? AND task_kind=? AND state NOT IN ('closed','cancelled') AND (reference_key=? OR (?='iqc' AND receipt_id=?)) ORDER BY seq LIMIT 1",
                (str(pid), task_kind, resolved.scope_key, task_kind, str(resolved.receipt_id) if resolved.receipt_id else None)).fetchone()
            evidence = resolved.model_dump(mode='json', exclude={'requirement_id','task_kinds'})
            items.append(dict(reference=ref.model_dump(mode='json'), evidence=evidence,
                              existing_task_id=existing[0] if existing else None, can_open=can_open and not existing))
        return dict(project_id=pid, project_version=project['version'], read_at=business_time(tx), task_kind=task_kind,
                    items=items[offset:offset+limit], total=len(items), limit=limit, offset=offset)
