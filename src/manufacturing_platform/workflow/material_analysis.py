"""Full-scope material issue classification from current workflow facts."""
import json
from decimal import Decimal

from .supply import _page_balances, amount
from .clock import business_time
from .material_eligibility import lot_unavailable_reason


def issue(code, title, kind, ident, quantity=None, unit=None, task=None, action='view_object'):
    return dict(code=code, title=title, object_kind=kind, object_id=ident,
                quantity=quantity, unit=unit, task_id=task['id'] if task else None,
                assignee_id=task['assignee_id'] if task else None,
                assignee_name='负责人待核对' if task else '待分派',
                proposed_assignee_id=task['proposed_assignee_id'] if task else None,
                proposed_assignee_name='负责人待核对' if task and task['proposed_assignee_id'] else None,
                next_action='view_task' if task else action)


def analyze(tx, pid, rows):
    balances = {}
    lot_cache = {}
    for start in range(0, len(rows), 300):
        balances.update(_page_balances(tx, pid, rows[start:start + 300], lot_cache))
    by_scope = {}
    for r in rows:
        by_scope.setdefault((r['lineage_id'], r['work_order_id'], r['material_id'], r['owner_id'], r['unit'], r['scale']), []).append(r)
    result = {r['id']: [] for r in rows}
    requirement_scopes = {r['id']: (r['lineage_id'], r['work_order_id'], r['material_id'], r['owner_id'], r['unit'], r['scale']) for r in tx.execute('SELECT * FROM requirements WHERE project_id=?', (pid,))}
    current_scopes = {}
    for r in tx.execute("""SELECT r.* FROM requirements r WHERE r.project_id=? AND r.plan_id=(SELECT p.id FROM plans p JOIN requirements candidate ON candidate.plan_id=p.id WHERE p.project_id=r.project_id AND candidate.work_order_id=r.work_order_id AND p.state='confirmed' ORDER BY p.accepted_seq DESC LIMIT 1)""", (pid,)):
        scope = requirement_scopes[r['id']]
        current_scopes.setdefault(scope, []).append(r['id'])
    current_ids = {rid for ids in current_scopes.values() for rid in ids}
    def scoped_rows(requirement_id):
        scope = requirement_scopes.get(requirement_id)
        if scope is None:
            return []
        current = current_scopes.get(scope, [])
        return [r for r in by_scope.get(scope, []) if r['id'] == requirement_id or (r['id'] in current_ids and len(current) == 1)]
    related_handoffs = {r['id']: [] for r in rows}
    tasks = list(tx.execute("SELECT * FROM material_tasks WHERE project_id=? AND state NOT IN ('closed','cancelled')", (pid,)))
    iqc_tasks = {t['receipt_id']: t for t in tasks if t['task_kind'] == 'iqc'}
    trace_tasks = {t['handoff_id']: t for t in tx.execute("SELECT * FROM material_tasks WHERE project_id=? AND task_kind='trace' AND state!='cancelled' ORDER BY seq", (pid,))}
    latest_times = {r['requirement_id']: r['need_at'] for r in tx.execute("SELECT e.requirement_id,e.need_at FROM material_need_time_events e JOIN (SELECT requirement_id,MAX(seq) seq FROM material_need_time_events WHERE project_id=? GROUP BY requirement_id) latest ON latest.seq=e.seq", (pid,))}
    unknown_quality = set()
    scope_ids = {}
    for row in rows:
        scope_ids.setdefault((row['lineage_id'], row['work_order_id'], row['material_id'], row['owner_id'], row['unit'], row['scale']), []).append(row['id'])
    quality = {r['material_lot_id']: r for r in tx.execute("""SELECT sr.material_lot_id,COUNT(i.id) inspection_count,COALESCE(SUM(i.accepted_atoms),0) accepted FROM effective_supply_receipts sr JOIN material_lots l ON l.id=sr.material_lot_id AND l.project_id=sr.project_id JOIN supply_commitments c ON c.id=sr.commitment_id AND c.project_id=sr.project_id JOIN requirements prior ON prior.id=c.requirement_id AND prior.project_id=c.project_id JOIN effective_iqc_results i ON i.receipt_id=sr.id AND i.project_id=sr.project_id WHERE sr.project_id=? AND sr.unit=l.unit AND prior.unit=l.unit AND prior.material_id=l.material_id AND prior.owner_id=l.owner_id AND prior.scale=l.scale GROUP BY sr.material_lot_id""", (pid,))}
    claims = {r['material_lot_id']: r['total'] for r in tx.execute("SELECT material_lot_id,SUM(confirmed_atoms) total FROM effective_reservations WHERE project_id=? AND authority_receipt_id IS NOT NULL GROUP BY material_lot_id", (pid,))}
    now = business_time(tx)
    for claim in tx.execute("""SELECT DISTINCT l.*,v.material_lot_id,v.work_order_id,prior.lineage_id,prior.material_id AS requirement_material,prior.owner_id AS requirement_owner,prior.unit AS requirement_unit,prior.scale AS requirement_scale FROM effective_reservations v JOIN requirements prior ON prior.id=v.requirement_id AND prior.project_id=v.project_id JOIN material_lots l ON l.id=v.material_lot_id AND l.project_id=v.project_id WHERE v.project_id=? AND v.authority_receipt_id IS NOT NULL AND v.confirmed_atoms>0""", (pid,)):
        if claim['id'] not in lot_cache:
            lot_cache[claim['id']] = lot_unavailable_reason(tx, pid, claim, now)
        if lot_cache[claim['id']]:
            for rid in scope_ids.get((claim['lineage_id'], claim['work_order_id'], claim['requirement_material'], claim['requirement_owner'], claim['requirement_unit'], claim['requirement_scale']), []):
                result[rid].append(issue('verification', lot_cache[claim['id']], 'material_lot', claim['id'], unit=claim['unit'], action='check_allocation'))
        fact = quality.get(claim['material_lot_id'])
        if (claim['material_id'], claim['owner_id'], claim['unit'], claim['scale']) != (claim['requirement_material'], claim['requirement_owner'], claim['requirement_unit'], claim['requirement_scale']) or not fact or fact['accepted'] < claims[claim['material_lot_id']]:
            unknown_quality.update(scope_ids.get((claim['lineage_id'], claim['work_order_id'], claim['requirement_material'], claim['requirement_owner'], claim['requirement_unit'], claim['requirement_scale']), []))
    duplicate_scopes = {(r['lineage_id'], r['work_order_id']) for r in tx.execute("""SELECT r.lineage_id,r.work_order_id FROM requirements r WHERE r.project_id=? AND r.plan_id=(SELECT p.id FROM plans p JOIN requirements candidate ON candidate.plan_id=p.id WHERE p.project_id=r.project_id AND candidate.work_order_id=r.work_order_id AND p.state='confirmed' ORDER BY p.accepted_seq DESC LIMIT 1) GROUP BY r.lineage_id,r.work_order_id HAVING COUNT(*)>1""", (pid,))}
    ambiguous_allocation = {r['id'] for r in rows if (r['lineage_id'], r['work_order_id']) in duplicate_scopes and Decimal(balances[r['id']].reserved) > 0}
    for r in rows:
        if r['id'] in ambiguous_allocation:
            result[r['id']].append(issue('verification', '共享预留归属待核对', 'requirement', r['id'], unit=r['unit'], action='check_allocation'))
        if r['id'] in unknown_quality:
            result[r['id']].append(issue('verification', '预留批次当前合格数量待核对', 'requirement', r['id'], unit=r['unit'], action='check_allocation'))
        if not latest_times.get(r['id']):
            result[r['id']].append(issue('verification', '物料需要时间待确认', 'requirement', r['id'], action='confirm_time'))
        bal = balances[r['id']]
        if Decimal(bal.shortage) > 0:
            result[r['id']].append(issue('shortage', '预留缺口', 'requirement', r['id'], bal.shortage, r['unit'], action='check_allocation'))
    for e in tx.execute("SELECT id,requirement_id FROM material_expedites WHERE project_id=? AND state='open'", (pid,)):
        for row in scoped_rows(e['requirement_id']):
            result[row['id']].append(issue('urgent', '在办急料', 'material_expedite', e['id'], action='expedite'))
    lot_scopes = set()
    receipts = tx.execute("""SELECT r.id,r.q_atoms,r.unit,r.material_lot_id,l.scale,prior.lineage_id,prior.work_order_id,prior.material_id,prior.owner_id,
        COALESCE((SELECT SUM(i.accepted_atoms+i.rejected_atoms) FROM effective_iqc_results i WHERE i.project_id=r.project_id AND i.receipt_id=r.id),0) checked
        FROM effective_supply_receipts r JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id
        JOIN requirements prior ON prior.id=c.requirement_id AND prior.project_id=c.project_id
        JOIN material_lots l ON l.id=r.material_lot_id AND l.project_id=r.project_id
        WHERE r.project_id=? AND r.unit=prior.unit AND l.unit=prior.unit AND l.material_id=prior.material_id AND l.owner_id=prior.owner_id AND l.scale=prior.scale""", (pid,))
    for rec in receipts:
        lot_scopes.add((rec['material_lot_id'], rec['lineage_id'], rec['work_order_id']))
        pending = rec['q_atoms'] - rec['checked']
        if pending <= 0: continue
        scope = (rec['lineage_id'], rec['work_order_id'], rec['material_id'], rec['owner_id'], rec['unit'], rec['scale'])
        for row in by_scope.get(scope, []):
            task = iqc_tasks.get(rec['id'])
            result[row['id']].append(issue('pending_iqc', '待检验', 'receipt', rec['id'], amount(pending, rec['scale']), rec['unit'], task, 'arrange_iqc'))
    lot_demands = {}
    for fact in tx.execute("""SELECT DISTINCT r.material_lot_id, current.work_order_id, current.id FROM effective_supply_receipts r
        JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id
        JOIN requirements prior ON prior.id=c.requirement_id AND prior.project_id=c.project_id
        JOIN requirements current ON current.project_id=prior.project_id AND current.lineage_id=prior.lineage_id AND current.work_order_id=prior.work_order_id
        JOIN material_lots l ON l.id=r.material_lot_id AND l.project_id=r.project_id
        WHERE r.project_id=? AND r.unit=current.unit AND l.unit=current.unit AND l.material_id=current.material_id AND l.owner_id=current.owner_id AND l.scale=current.scale
          AND current.plan_id=(SELECT p.id FROM plans p JOIN requirements candidate ON candidate.plan_id=p.id WHERE p.project_id=current.project_id AND candidate.work_order_id=current.work_order_id AND p.state='confirmed' ORDER BY p.accepted_seq DESC LIMIT 1)""", (pid,)):
        lot_demands.setdefault((fact['material_lot_id'], fact['work_order_id']), set()).add(fact['id'])
    # Evidence links are exclusive; sums are valid only within their existing trace task.
    supplements = {}
    for link in tx.execute("""SELECT e.task_id,h.receipt_json FROM material_task_evidence e JOIN material_handoffs h ON h.id=e.handoff_id AND h.project_id=e.project_id WHERE e.project_id=? AND h.state!='cancelled'""", (pid,)):
        supplements.setdefault(link['task_id'], []).append(json.loads(link['receipt_json']) if link['receipt_json'] else None)
    by_work_lot = {}
    for row in rows:
        key = (row['work_order_id'], row['material_id'], row['owner_id'], row['unit'])
        by_work_lot.setdefault(key, []).append(row)
    for hand in tx.execute("""SELECT h.*,l.material_id,l.owner_id,l.unit,l.scale FROM material_handoffs h JOIN material_lots l ON l.id=h.material_lot_id AND l.project_id=h.project_id WHERE h.project_id=? AND h.state!='cancelled'""", (pid,)):
        candidates = [r for r in by_work_lot.get((hand['work_order_id'], hand['material_id'], hand['owner_id'], hand['unit']), []) if r['scale'] == hand['scale']]
        payload = json.loads(hand['payload_json'])
        signed = json.loads(hand['receipt_json']) if hand['receipt_json'] else None
        task = trace_tasks.get(hand['id'])
        scoped = (task['requirement_id'] if task else None) or (signed.get('requirement_id') if signed and signed.get('receipt_use') == 'line_side' else None)
        if scoped:
            target_ids = {r['id'] for r in scoped_rows(scoped)}
            candidates = [r for r in candidates if r['id'] in target_ids]
            for row in candidates:
                related_handoffs[row['id']].append(hand['id'])
            if len(candidates) != 1:
                for row in candidates:
                    result[row['id']].append(issue('verification', '交接归属待核对', 'material_handoff', hand['id'], unit=hand['unit'], action='check_allocation'))
                continue
        else:
            candidates = [r for r in candidates if (hand['material_lot_id'], r['lineage_id'], r['work_order_id']) in lot_scopes]
        if not scoped and len(lot_demands.get((hand['material_lot_id'], hand['work_order_id']), set())) != 1:
            for row in candidates:
                result[row['id']].append(issue('verification', '交接归属待核对', 'material_handoff', hand['id'], unit=hand['unit'], action='check_allocation'))
            continue
        if not candidates: continue
        if signed and signed['received_location'] != payload['to_location']:
            result[candidates[0]['id']].append(issue('verification', '签收地点待核对', 'material_handoff', hand['id'], unit=hand['unit'], task=task, action='view_object'))
            continue
        sent = Decimal(payload['quantity'])
        received = Decimal(signed['received_quantity']) if signed else Decimal(0)
        if task and signed:
            linked = supplements.get(task['id'], [])
            if all(item and item['received_location'] == payload['to_location'] for item in linked):
                received += sum((Decimal(item['received_quantity']) for item in linked), Decimal(0))
        if received < sent:
            result[candidates[0]['id']].append(issue('unreceived', '交接未足额签收', 'material_handoff', hand['id'], str(sent-received), hand['unit'], task, 'trace'))
    return balances, result, unknown_quality | ambiguous_allocation, related_handoffs
