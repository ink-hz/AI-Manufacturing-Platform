"""Read-only graphs beside the existing material quantities.

Values are the existing balance/read projection, never an alternate calculator.
Complete enumeration means persisted platform records only, not external coverage.
"""
import json
from decimal import Decimal

from .material_source_reader import MaterialSources, scope
from .quantity_provenance import quantity
from .supply import amount


def _reader(tx, project_id, reader):
    if reader is not None:
        if reader.tx is not tx or reader.pid != str(project_id):
            raise ValueError('Provenance reader must share transaction and project')
        return reader
    return MaterialSources(tx, project_id)


def _required(reader, row):
    if row['id'] not in reader.required_cache:
        plan = reader.one('plans', row['plan_id'])
        wo = reader.one('work_orders', row['work_order_id'])
        source = json.loads(plan['source_json']) if plan else None
        result = [reader.leaf(source, 'requirement', row['id'],
            f'required; plan={row["plan_id"]}; scope={json.dumps(scope(row))}; execution={row["execution_scope"]}',
            amount(row['q_atoms'], row['scale']), row['unit'])]
        if plan:
            result.append(reader.row_leaf(plan, 'plan', 'requirement plan basis'))
            # Only the inputs for this work order; unrelated plan lines do not
            # contaminate its quantities. Preserve the exact stored versions.
            inputs = json.loads(plan['inputs_json'])
            for order in inputs.get('input_order_versions', []):
                if wo and str(order['order_line_id']) == wo['order_line_id']:
                    result.append(reader.leaf(source, 'plan_input', f'{plan["id"]}:order:{order["order_line_id"]}:{order["version"]}', 'plan order version basis'))
            for revision in inputs.get('input_revision_ids', []):
                if wo and str(revision) == wo['revision_id']:
                    result.append(reader.leaf(source, 'plan_input', f'{plan["id"]}:revision:{revision}', 'plan revision basis'))
        if wo:
            result.append(reader.row_leaf(wo, 'work_order', 'requirement work order association'))
        reader.required_cache[row['id']] = result
    return reader.required_cache[row['id']]


def _receipt(reader, receipt_id):
    if receipt_id in reader.receipt_cache:
        return reader.receipt_cache[receipt_id]
    row = reader.one('supply_receipts', receipt_id)
    if row is None:
        raise ValueError('Receipt outside authorized project')
    lot = reader.one('material_lots', row['material_lot_id'])
    commitment = reader.one('supply_commitments', row['commitment_id'])
    prior = reader.one('requirements', commitment['requirement_id'])
    scale, unit = lot['scale'], row['unit']
    associations = _required(reader, prior) + [reader.row_leaf(lot, 'material_lot', 'receipt lot identity')]
    original = [reader.row_leaf(row, 'receipt', 'original received', amount(row['q_atoms'], scale), unit)]
    original += reader.confirmation_leaves('receipt', row['id'], row['id'])
    original += reader.linked_integrations('receipt', row['id'])
    corrections = reader.by('source_corrections', 'receipt_id', row['id'])
    received = original + [reader.correction(c, 'received_delta', scale, unit) for c in corrections]
    effective = row['q_atoms'] + sum(c['received_delta'] for c in corrections)
    inspection_association = [reader.row_leaf(row, 'receipt', 'inspection receipt association')]
    accepted, rejected = [], []
    accepted_atoms, rejected_atoms = 0, 0
    for inspection in reader.by('iqc_results', 'receipt_id', row['id']):
        confirmations = reader.confirmation_leaves('iqc', row['id'], inspection['id'])
        corrections_i = [c for c in reader.by('source_corrections', 'iqc_id', inspection['id']) if c['receipt_id'] == row['id']]
        for target, field in ((accepted, 'accepted'), (rejected, 'rejected')):
            # Original event and source confirmation remain separate; stored
            # created_at is collection time, never invented occurrence time.
            target.append(reader.inspection(inspection, field, amount(inspection[field + '_atoms'], scale), unit))
            target.extend(confirmations)
            target.extend(reader.correction(c, field + '_delta', scale, unit) for c in corrections_i)
        accepted_atoms += inspection['accepted_atoms'] + sum(c['accepted_delta'] for c in corrections_i)
        rejected_atoms += inspection['rejected_atoms'] + sum(c['rejected_delta'] for c in corrections_i)
    # A known local empty sum is not evidence of complete source-system IQC.
    empty = [reader.local('receipt_inspection_scope', row['id'], 'no persisted inspection', '0', unit)]
    facts = {
        'original_quantity': quantity(amount(row['q_atoms'], scale), unit, 'original received', original + associations),
        'quantity': quantity(amount(effective, scale), unit, 'effective received', received + associations),
        'qualified': quantity(amount(accepted_atoms, scale), unit, 'recorded accepted IQC', (accepted or empty) + associations + inspection_association),
        'accepted': quantity(amount(accepted_atoms, scale), unit, 'recorded accepted IQC', (accepted or empty) + associations + inspection_association),
        'rejected': quantity(amount(rejected_atoms, scale), unit, 'recorded rejected IQC', (rejected or empty) + associations + inspection_association),
        'uninspected': quantity(amount(effective-accepted_atoms-rejected_atoms, scale), unit,
                               'received minus recorded inspections', received + accepted + rejected + (empty if not accepted else []) + associations),
    }
    reader.receipt_cache[row['id']] = facts
    return facts


def receipt_quantities(tx, project_id, receipt_id, *, reader=None):
    return _receipt(_reader(tx, project_id, reader), str(receipt_id))


def _scope_indexes(reader):
    if 'commitment_scopes' in reader.indexes:
        return
    from collections import defaultdict
    commitments, reservations = defaultdict(list), defaultdict(list)
    for row in reader.rows('supply_commitments'):
        prior = reader.one('requirements', row['requirement_id'])
        if prior:
            commitments[scope(prior)].append(row)
    for row in reader.rows('reservations'):
        prior = reader.one('requirements', row['requirement_id'])
        if prior and row['authority_receipt_id'] is not None:
            reservations[scope(prior, row['work_order_id'])].append(row)
    reader.indexes['commitment_scopes'] = commitments
    reader.indexes['reservation_scopes'] = reservations


def _eligibility(reader, lot_id):
    if lot_id in reader.eligibility_cache:
        return reader.eligibility_cache[lot_id]
    lot = reader.one('material_lots', lot_id)
    result = [reader.row_leaf(lot, 'material_lot', f'eligibility state={lot["state"]}; expiry={lot["expiry"]}'),
              reader.local('lot_eligibility', lot_id,
                'eligibility evaluated by existing hold rules; historical ownership/stock proof coverage unknown')]
    # Quality and shared occupancy consult the whole lot, including claims outside
    # the returned work order/page. Include original claims even if fully released.
    for claim in reader.by('reservations', 'material_lot_id', lot_id):
        if claim['authority_receipt_id'] is not None:
            result += reader.reservation(claim)
    for rec in reader.by('supply_receipts', 'material_lot_id', lot_id):
        commitment = reader.one('supply_commitments', rec['commitment_id'])
        prior = reader.one('requirements', commitment['requirement_id'])
        if (rec['unit'] == lot['unit'] and (prior['material_id'], prior['owner_id'], prior['unit'], prior['scale'])
            == (lot['material_id'], lot['owner_id'], lot['unit'], lot['scale'])):
            facts = _receipt(reader, rec['id'])
            result += facts['quantity'].source_refs + facts['qualified'].source_refs + facts['rejected'].source_refs
    for row in reader.by('effective_material_movements', 'material_lot_id', lot_id):
        result.append(reader.row_leaf(row, 'material_movement', f'eligibility {row["movement"]}', amount(row['q_atoms'], lot['scale']), lot['unit']))
    for row in reader.by('ownership_reconciliations', 'material_lot_id', lot_id):
        result.append(reader.row_leaf(row, 'ownership_reconciliation', 'eligibility ownership evidence'))
    for row in reader.by('material_consumption', 'lot_id', lot_id):
        event = reader.one('execution_events', row['execution_event_id'])
        result.append(reader.leaf(json.loads(event['source_json']) if event else None, 'material_consumption', row['id'],
                                  'eligibility consumption', amount(row['q_atoms'], lot['scale']), lot['unit']))
    for row in reader.by('freeze_members', 'lot_id', lot_id):
        request = reader.one('freeze_requests', row['request_id'])
        result.append(reader.local('freeze_request', row['request_id'],
                                  f'eligibility freeze request; exchange={request["exchange_id"]}' if request else 'eligibility freeze request'))
    for claim in reader.by('reservations', 'material_lot_id', lot_id):
        for proof in reader.by('stock_basis_proofs', 'reservation_id', claim['id']):
            result.append(reader.local('stock_basis_proof', proof['id'], f'eligibility stock proof; exchange={proof["exchange_id"]}'))
    result += reader.linked_integrations('material_lot', lot_id)
    reader.eligibility_cache[lot_id] = result
    return result


def requirement_quantities(tx, project_id, rows, balances, unknown_quality, *, reader=None):
    reader = _reader(tx, project_id, reader)
    _scope_indexes(reader)
    result = {}
    for row in rows:
        required = _required(reader, row)
        inputs = {k: [] for k in ('received', 'in_transit', 'qualified', 'rejected', 'reserved')}
        for commitment in reader.indexes['commitment_scopes'].get(scope(row), []):
            inputs['in_transit'].append(reader.row_leaf(commitment, 'commitment', 'current promise',
                amount(commitment['current_q_atoms'], row['scale']), row['unit']))
            prior = reader.one('requirements', commitment['requirement_id'])
            for k in ('received', 'in_transit', 'qualified', 'rejected'):
                inputs[k] += _required(reader, prior)
            for rec in reader.by('supply_receipts', 'commitment_id', commitment['id']):
                facts = _receipt(reader, rec['id'])
                inputs['received'] += facts['quantity'].source_refs
                inputs['in_transit'] += facts['quantity'].source_refs
                inputs['qualified'] += facts['qualified'].source_refs
                inputs['rejected'] += facts['rejected'].source_refs
        eligibility = []
        for reservation in reader.indexes['reservation_scopes'].get(scope(row), []):
            inputs['reserved'] += reader.reservation(reservation)
            eligibility += _eligibility(reader, reservation['material_lot_id'])
        bal = balances[row['id']].model_dump(mode='json')
        values = {'required': quantity(bal['required'], row['unit'], 'required', required)}
        for k, sources in inputs.items():
            values[k] = quantity(bal[k], row['unit'], k, required + sources)
        derived = required + inputs['reserved'] + eligibility
        values['shortage'] = quantity(bal['shortage'], row['unit'], 'required minus usable confirmed reservation', derived)
        value = None if row['id'] in unknown_quality else amount(row['q_atoms'] - int(Decimal(bal['shortage']) * 10 ** row['scale']), row['scale'])
        if row['id'] in unknown_quality:
            derived = derived + [reader.local('requirement_eligibility', row['id'], 'quality or allocation remains unresolved')]
        values['confirmed_satisfied'] = quantity(value, row['unit'], 'capped usable reserved satisfaction', derived,
                                                fact_role='unknown' if value is None else 'confirmed')
        result[row['id']] = values
    return result


def handoff_quantities(tx, project_id, handoff, *, reader=None):
    reader = _reader(tx, project_id, reader)
    if not isinstance(handoff, dict):
        handoff = handoff.model_dump(mode='json')
    ident, unit = str(handoff['id']), handoff['unit']
    sent = [reader.leaf(handoff['source'], 'material_handoff', ident, 'sender declared quantity', str(handoff['quantity']), unit)]
    signed = handoff.get('receipt')
    value = str(signed['received_quantity']) if signed else None
    received = [reader.local('material_handoff_receipt', ident, 'designated receiver declared quantity', value, unit,
        manual=bool(signed), actor=signed.get('actor_id') if signed else None,
        collected_at=signed.get('recorded_at') if signed else None,
        occurred_at=signed.get('occurred_at') if signed else None, complete=bool(signed))]
    if signed:
        received.append(reader.local('handoff_receipt_use', ident,
            f'receipt_use={signed.get("receipt_use", "unspecified")}; requirement={signed.get("requirement_id")}; location={signed["received_location"]}',
            manual=True, actor=signed.get('scope_actor_id') or signed['actor_id'],
            collected_at=signed.get('scope_recorded_at') or signed['recorded_at'], complete=True))
    return {'quantity': quantity(str(handoff['quantity']), unit, 'sender declared quantity', sent),
            'received_quantity': quantity(value, unit, 'designated receiver declared quantity', received,
                                         fact_role='confirmed' if signed else 'unknown')}


def issue_quantity(reader, issue, requirement, values):
    if issue['quantity'] is None:
        return None
    if issue['code'] == 'shortage':
        return values['shortage']
    if issue['code'] == 'pending_iqc':
        return _receipt(reader, issue['object_id'])['uninspected']
    sources = []
    if issue['code'] == 'unreceived':
        raw = reader.one('material_handoffs', issue['object_id'])
        def hand_sources(row):
            hand = json.loads(row['payload_json'])
            hand['receipt'] = json.loads(row['receipt_json']) if row['receipt_json'] else None
            facts = handoff_quantities(reader.tx, reader.pid, hand, reader=reader)
            return [s for q in facts.values() for s in q.source_refs]
        sources += hand_sources(raw)
        task_rows = [t for t in reader.by('material_tasks', 'handoff_id', raw['id']) if t['task_kind'] == 'trace' and t['state'] != 'cancelled']
        if task_rows:
            task = task_rows[-1]
            sources.append(reader.local('material_task', task['id'], 'exclusive supplemental handoff group'))
            for link in reader.by('material_task_evidence', 'task_id', task['id']):
                extra = reader.one('material_handoffs', link['handoff_id'])
                if extra and extra['state'] != 'cancelled':
                    sources += hand_sources(extra)
                    sources.append(reader.local('material_task_evidence', f'{task["id"]}:{link["handoff_id"]}', 'exclusive supplemental handoff link'))
        # Actual association used by analyze: task/receipt scope or same-lot demand.
        sources += _required(reader, requirement)
        for rec in reader.by('supply_receipts', 'material_lot_id', raw['material_lot_id']):
            commitment = reader.one('supply_commitments', rec['commitment_id'])
            prior = reader.one('requirements', commitment['requirement_id'])
            if scope(prior) == scope(requirement):
                sources += _receipt(reader, rec['id'])['quantity'].source_refs
    return quantity(issue['quantity'], issue['unit'], issue['code'], sources)


def work_order_quantities(reader, item):
    row = reader.one('work_orders', item['id'])
    return {name: quantity(item[name], item['unit'], name,
            [reader.row_leaf(row, 'work_order', name, item[name], item['unit'])])
            for name in ('quantity', 'trial_quantity')}


def project_source_modes(tx, project_id):
    """Legacy overview scope: all persisted project source records, no 501 cap."""
    reader = MaterialSources(tx, project_id)
    sources = []
    for table in ('work_orders', 'plans', 'supply_commitments', 'supply_promise_revisions', 'material_lots',
                  'supply_receipts', 'material_movements', 'ownership_reconciliations'):
        sources += [reader.row_leaf(row, table, 'project source record') for row in reader.rows(table)]
    for table in ('material_handoffs', 'material_expedites', 'issue_marks'):
        for row in reader.rows(table):
            sources.append(reader.leaf(json.loads(row['payload_json']).get('source'), table, row['id'], 'project source record'))
    for row in reader.rows('source_confirmations'):
        sources.append(reader.leaf(json.loads(row['source_json']), 'source_confirmation', row['seq'], 'project source record'))
    for row in reader.rows('iqc_results'):
        sources.append(reader.inspection(row, 'project local inspection'))
    for row in reader.rows('source_corrections'):
        receipt = reader.one('supply_receipts', row['receipt_id'])
        lot = reader.one('material_lots', receipt['material_lot_id'])
        sources += [reader.correction(row, field, lot['scale'], lot['unit']) for field in ('received_delta', 'accepted_delta', 'rejected_delta')]
    for row in reader.rows('reservations'):
        if row['authority_receipt_id'] is not None:
            sources += reader.reservation(row)
    for row, fact in reader.integrations().values():
        sources.append(reader.integration_leaf(row, fact, 'project source record'))
    return sorted({'api' if s.origin == 'native' else s.origin for s in sources})
