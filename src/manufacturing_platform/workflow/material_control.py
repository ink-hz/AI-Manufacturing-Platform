"""Non-accounting material read projections from authorized workflow facts."""
import json
from decimal import Decimal
from datetime import datetime

from .authorization import effective_permissions, require_project
from uuid import UUID
from .clock import business_time
from .contracts import DomainError
from .material_control_models import MaterialControlPage
from .supply import amount, current_plan_id, receipt_presentation
from .material_analysis import analyze
from .material_source_reader import MaterialSources
from .material_provenance import (requirement_quantities, receipt_quantities, handoff_quantities,
    work_order_quantities, issue_quantity, project_source_modes)
from .quantity_provenance import source_modes

ISSUE = "Evidence is bounded and may not represent complete external supply or inventory."

# Match supply.current_plan_id: the latest confirmed plan containing this work order.
_CURRENT_REQUIREMENT = """plan_id = (
    SELECT p.id FROM plans p JOIN requirements candidate ON candidate.plan_id=p.id
    WHERE p.project_id=requirements.project_id
      AND candidate.work_order_id=requirements.work_order_id AND p.state='confirmed'
    ORDER BY p.accepted_seq DESC LIMIT 1
)"""


def _count(tx, table, pid, extra="", args=()):
    return tx.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=? {extra}", (pid, *args)).fetchone()[0]


def _unreceived_handoffs(tx, pid):
    """Count unsigned and short-signed quantities with exact decimal comparison."""
    count = 0
    for row in tx.execute("SELECT payload_json, receipt_json FROM material_handoffs WHERE project_id=? AND state!='cancelled'", (pid,)):
        if row["receipt_json"] is None:
            count += 1
            continue
        sent = Decimal(json.loads(row["payload_json"])["quantity"])
        received = Decimal(json.loads(row["receipt_json"])["received_quantity"])
        if received < sent:
            count += 1
    return count



def overview(service, actor, limit, offset):
    service._pagination(limit, offset)
    with service.store.transaction() as tx:
        if actor.configuration_admin:
            sql, args = "SELECT id FROM projects", ()
        else:
            sql, args = "SELECT project_id FROM project_grants WHERE user_id=? AND active=1 AND roles_json!='[]'", (str(actor.user_id),)
        total = tx.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
        ids = tx.execute(f"{sql} ORDER BY 1 LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        now = business_time(tx).isoformat()
        items = []
        for entry in ids:
            pid = entry[0]
            p = require_project(tx, actor, pid)
            items.append(dict(project_id=pid, name=p['name'], customer_id=p['customer_id'], product=p['product'],
                work_order_count=_count(tx, 'work_orders', pid), requirement_count=_count(tx, 'requirements', pid, f'AND {_CURRENT_REQUIREMENT}'),
                open_expedite_count=_count(tx, 'material_expedites', pid, "AND state='open'"),
                unreceived_handoff_count=_unreceived_handoffs(tx, pid),
                open_material_task_count=_count(tx, 'material_tasks', pid, "AND state NOT IN ('closed','cancelled')"),
                coverage_issues=[ISSUE], source_modes=project_source_modes(tx, pid), source_modes_scope='project_source_records'))
        return dict(items=items, total=total, limit=limit, offset=offset, read_at=now)


def _value(tx, pid, kind, ident, project):
    """Read only bounded value fields, leaving object history to its detail route."""
    if kind == "work_order":
        from .orders import amount as project_amount
        row = tx.execute("SELECT * FROM work_orders WHERE project_id=? AND id=?", (pid, ident)).fetchone()
        return dict(id=ident, kind=kind, order_line_id=row["order_line_id"], revision_id=row["revision_id"],
                    quantity=project_amount(row["q_atoms"], project), unit=row["unit"], purpose=row["purpose"],
                    trial_quantity=project_amount(row["trial_q_atoms"], project), source=json.loads(row["source_json"]),
                    planned_start=row["planned_start"], planned_end=row["planned_end"])
    if kind == "receipt":
        row = tx.execute("SELECT r.*, l.scale, original.q_atoms original_q_atoms FROM effective_supply_receipts r JOIN material_lots l ON l.id=r.material_lot_id AND l.project_id=r.project_id JOIN supply_receipts original ON original.id=r.id AND original.project_id=r.project_id WHERE r.project_id=? AND r.id=?", (pid, ident)).fetchone()
        accepted, rejected = tx.execute("SELECT COALESCE(SUM(accepted_atoms),0), COALESCE(SUM(rejected_atoms),0) FROM effective_iqc_results WHERE project_id=? AND receipt_id=?", (pid, ident)).fetchone()
        return dict(id=ident, kind=kind, commitment_id=row["commitment_id"], material_lot_id=row["material_lot_id"],
                    quantity=amount(row["q_atoms"], row["scale"]), original_quantity=amount(row["original_q_atoms"], row["scale"]),
                    unit=row["unit"], source=json.loads(row["source_json"]), accepted=amount(accepted, row["scale"]),
                    qualified=amount(accepted, row["scale"]), rejected=amount(rejected, row["scale"]),
                    uninspected=amount(row["q_atoms"]-accepted-rejected, row["scale"]),
                    **receipt_presentation(row["q_atoms"], accepted, rejected))
    if kind == "material_handoff":
        from .material_handoff_reader import value
        table = "material_handoffs"
    else:
        from .issue_marks import value
        table = "issue_marks"
    row = tx.execute(f"SELECT * FROM {table} WHERE project_id=? AND id=?", (pid, ident)).fetchone()
    return value(tx, pid, row).model_dump(mode="json")


def _expedite_preview(tx, pid, ident):
    """Read a bounded progress preview without invoking the unbounded detail reader."""
    from .expedite_models import MaterialExpedite

    row = tx.execute("SELECT * FROM material_expedites WHERE project_id=? AND id=?", (pid, ident)).fetchone()
    payload = json.loads(row["payload_json"])
    scope = (pid, payload["requirement_id"])
    queries = {
        "receipt_at": ("SELECT r.created_at FROM supply_receipts r JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id WHERE r.project_id=? AND c.requirement_id=? ORDER BY r.created_at,r.id LIMIT 1", scope),
        "inspection_at": ("SELECT i.created_at FROM iqc_results i JOIN supply_receipts r ON r.id=i.receipt_id AND r.project_id=i.project_id JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id WHERE i.project_id=? AND c.requirement_id=? ORDER BY i.created_at,i.id LIMIT 1", scope),
        "arrival_at": ("SELECT json_extract(a.payload_json,'$.source.occurred_at') occurred FROM arrivals a JOIN arrival_matches m ON m.arrival_id=a.id AND m.project_id=a.project_id JOIN supply_receipts r ON r.id=m.receipt_id AND r.project_id=m.project_id JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id WHERE m.project_id=? AND c.requirement_id=? AND NOT EXISTS (SELECT 1 FROM arrival_matches newer WHERE newer.project_id=m.project_id AND newer.arrival_id=m.arrival_id AND newer.seq>m.seq) ORDER BY julianday(occurred),a.id LIMIT 1", scope),
        "handoff_at": ("SELECT json_extract(h.receipt_json,'$.occurred_at') occurred FROM material_handoffs h JOIN supply_receipts r ON r.material_lot_id=h.material_lot_id AND r.project_id=h.project_id JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id WHERE h.project_id=? AND c.requirement_id=? AND h.work_order_id=? AND h.state IN ('received','resolved') AND CAST(json_extract(h.receipt_json,'$.received_quantity') AS NUMERIC)>0 ORDER BY julianday(occurred),h.seq LIMIT 1", (*scope, payload["work_order_id"])),
    }
    milestones = {"opened_at": payload["recorded_at"]}
    for name, (sql, args) in queries.items():
        fact = tx.execute(sql, args).fetchone()
        milestones[name] = fact[0] if fact else None
    progress_total = tx.execute("SELECT COUNT(*) FROM expedite_progress WHERE project_id=? AND expedite_id=?", (pid, ident)).fetchone()[0]
    progress = [json.loads(r[0]) for r in tx.execute("SELECT payload_json FROM expedite_progress WHERE project_id=? AND expedite_id=? ORDER BY seq LIMIT 20", (pid, ident))]
    value = MaterialExpedite(**payload, state=row["state"], milestones=milestones, progress=progress,
                             closure=json.loads(row["closure_json"]) if row["closure_json"] else None)
    return {**value.model_dump(mode="json"), "progress_total": progress_total, "progress_truncated": progress_total > len(progress)}


def project_view(service, actor, project_id, limit, offset, work_order_id=None, requirement_id=None, search="", problem="all"):
    service._pagination(limit, offset)
    pid = str(project_id)
    with service.store.transaction() as tx:
        p = require_project(tx, actor, project_id)
        if work_order_id and not tx.execute('SELECT 1 FROM work_orders WHERE project_id=? AND id=?', (pid, str(work_order_id))).fetchone():
            raise DomainError('NOT_FOUND', 404, 'Workflow resource not found')
        if requirement_id:
            req = tx.execute('SELECT work_order_id FROM requirements WHERE project_id=? AND id=?', (pid, str(requirement_id))).fetchone()
            if not req or (work_order_id and req['work_order_id'] != str(work_order_id)):
                raise DomainError('NOT_FOUND', 404, 'Workflow resource not found')
        where, args = 'project_id=?', [pid]
        if work_order_id:
            where += ' AND work_order_id=?'; args.append(str(work_order_id))
        if requirement_id:
            where += ' AND id=?'; args.append(str(requirement_id))
        else:
            where += f' AND {_CURRENT_REQUIREMENT}'
        if search:
            escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where += " AND (material_id LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM work_orders w WHERE w.project_id=requirements.project_id AND w.id=requirements.work_order_id AND w.source_external_id LIKE ? ESCAPE '\\'))"
            args.extend([f'%{escaped}%', f'%{escaped}%'])
        scoped = tx.execute(f'SELECT requirements.*,(SELECT cutoff FROM plans p WHERE p.id=requirements.plan_id) cutoff,(SELECT source_version FROM plans p WHERE p.id=requirements.plan_id) source_version FROM requirements WHERE {where} ORDER BY requirements.created_at,requirements.id', args).fetchall()
        balances, analysis, unknown_quality, related_handoffs = analyze(tx, pid, scoped)
        problem_counts = {key: sum(any(item['code'] == key for item in analysis[r['id']]) for r in scoped) for key in ('shortage','urgent','pending_iqc','unreceived','verification')}
        problem_counts['attention'] = sum(bool(analysis[r['id']]) for r in scoped)
        problem_counts['all'] = len(scoped)
        matching = [r for r in scoped if problem == 'all' or (problem == 'attention' and analysis[r['id']]) or any(item['code'] == problem for item in analysis[r['id']])]
        total = len(matching)
        rows = matching[offset:offset + limit]
        reader = MaterialSources(tx, pid)
        projected = requirement_quantities(tx, pid, rows, balances, unknown_quality, reader=reader)
        all_quantities = []
        now = business_time(tx)
        need_times = {}
        if rows:
            ids = [r['id'] for r in rows]
            slots = ','.join('?' for _ in ids)
            need_times = {r['requirement_id']: r for r in tx.execute(
                f"SELECT e.requirement_id,e.need_at,counts.n FROM material_need_time_events e JOIN (SELECT requirement_id,MAX(seq) latest,COUNT(*) n FROM material_need_time_events WHERE project_id=? AND requirement_id IN ({slots}) GROUP BY requirement_id) counts ON counts.latest=e.seq", (pid, *ids))}
        requirements, expedites, handoffs, receipts, issue_marks, work_orders = [], [], [], [], [], []
        seen = {name: set() for name in ('work_orders', 'expedites', 'handoffs', 'receipts', 'issue_marks')}
        issues = [ISSUE, "Work order readiness and execution history, and receipt correction and confirmation history, are available in object detail."]
        if total > len(rows):
            issues.append('Requirement page is partial; related evidence covers only returned requirements.')
        def add(target, kind, ident, extra=None):
            if ident in seen[target]: return
            seen[target].add(ident)
            item = (_expedite_preview(tx, pid, ident) if kind == 'material_expedite'
                    else _value(tx, pid, kind, ident, p))
            if kind == 'material_expedite' and item['progress_truncated']:
                issues.append(f'Expedite {ident} progress preview is truncated; use object detail for full progress.')
            if kind == 'work_order':
                facts = work_order_quantities(reader, item)
            elif kind == 'receipt':
                facts = receipt_quantities(tx, pid, ident, reader=reader)
            elif kind == 'material_handoff':
                facts = handoff_quantities(tx, pid, item, reader=reader)
            else:
                facts = None
            if facts is not None:
                item['quantities'] = {k: q.model_dump(mode='json') for k, q in facts.items()}
                all_quantities.extend(facts.values())
            if extra: item.update(extra)
            locals_map[target].append(item)
        locals_map = dict(work_orders=work_orders, expedites=expedites, handoffs=handoffs, receipts=receipts, issue_marks=issue_marks)
        for row in rows:
            rid, wid = row['id'], row['work_order_id']
            wo = tx.execute('SELECT * FROM work_orders WHERE project_id=? AND id=?', (pid, wid)).fetchone()
            add('work_orders', 'work_order', wid, {'title': wo['source_external_id']})
            bal = balances[rid].model_dump(mode='json')
            exp = tx.execute('SELECT id FROM material_expedites WHERE project_id=? AND requirement_id=? ORDER BY seq LIMIT 201', (pid, rid)).fetchall()
            rec = tx.execute('SELECT r.id,r.material_lot_id FROM effective_supply_receipts r JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id JOIN requirements prior ON prior.id=c.requirement_id AND prior.project_id=c.project_id WHERE r.project_id=? AND prior.lineage_id=? AND prior.work_order_id=? AND prior.material_id=? AND prior.owner_id=? AND prior.unit=? AND prior.scale=? ORDER BY r.created_at,r.id LIMIT 201', (pid, row['lineage_id'], wid, row['material_id'], row['owner_id'], row['unit'], row['scale'])).fetchall()
            marks = tx.execute('SELECT id FROM issue_marks WHERE project_id=? AND requirement_id=? ORDER BY seq LIMIT 201', (pid, rid)).fetchall()
            hand = tx.execute('SELECT DISTINCT h.id,h.seq FROM material_handoffs h JOIN effective_supply_receipts r ON r.project_id=h.project_id AND r.material_lot_id=h.material_lot_id JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id JOIN requirements prior ON prior.id=c.requirement_id AND prior.project_id=c.project_id JOIN material_lots l ON l.id=h.material_lot_id AND l.project_id=h.project_id WHERE r.unit=prior.unit AND l.material_id=prior.material_id AND l.owner_id=prior.owner_id AND l.unit=prior.unit AND l.scale=prior.scale AND h.project_id=? AND prior.lineage_id=? AND h.work_order_id=? AND prior.work_order_id=? AND prior.material_id=? AND prior.owner_id=? AND prior.unit=? AND prior.scale=? ORDER BY h.seq LIMIT 201', (pid, row['lineage_id'], wid, wid, row['material_id'], row['owner_id'], row['unit'], row['scale'])).fetchall()
            exp = list(dict.fromkeys([x['id'] for x in exp] + [i['object_id'] for i in analysis[rid] if i['code'] == 'urgent']))
            hand = list(dict.fromkeys([x['id'] for x in hand] + related_handoffs[rid]))
            if any(len(x) > 200 for x in (exp, rec, marks, hand)):
                issues.append(f'Related evidence for requirement {rid} is truncated at 200 per type.')
            for x in exp[:200]: add('expedites', 'material_expedite', x)
            for x in rec[:200]:
                add('receipts', 'receipt', x['id'])
            for x in marks[:200]: add('issue_marks', 'issue_mark', x['id'])
            for x in hand[:200]: add('handoffs', 'material_handoff', x)
            need_event = need_times.get(rid)
            need_count = need_event['n'] if need_event else 0
            need_at = need_event['need_at'] if need_event and need_event['need_at'] else wo['planned_start']
            timing_risk = 'unknown'
            if need_at and any(item['code'] in ('shortage', 'pending_iqc', 'unreceived', 'urgent') for item in analysis[rid]):
                parsed_need = datetime.fromisoformat(need_at.replace('Z', '+00:00'))
                if parsed_need.utcoffset() is not None and parsed_need <= now:
                    timing_risk = 'need_time_passed'
            all_quantities.extend(projected[rid].values())
            for item in analysis[rid]:
                fact = issue_quantity(reader, item, row, projected[rid])
                if fact is not None:
                    item['quantity_fact'] = fact.model_dump(mode='json')
                    all_quantities.append(fact)
            requirements.append(dict(quantities={k: q.model_dump(mode='json') for k, q in projected[rid].items()}, id=rid, work_order_id=wid, state='required' if row['plan_id'] == current_plan_id(tx, pid, wid) else 'superseded', material_id=row['material_id'], owner_id=row['owner_id'], unit=row['unit'], execution_scope=row['execution_scope'],
                **{k: bal[k] for k in ('required', 'received', 'qualified', 'rejected', 'reserved', 'shortage', 'in_transit')},
                confirmed_satisfied=None if rid in unknown_quality else amount(row['q_atoms'] - int(Decimal(bal['shortage']) * 10 ** row['scale']), row['scale']), issues=analysis[rid],
                need_at=need_at, need_at_basis='manual_requirement' if need_event and need_event['need_at'] else 'work_order_planned_start_proxy', need_time_history_count=need_count, timing_risk=timing_risk, coverage_issues=[ISSUE],
                expedite_ids=exp[:200], receipt_ids=[x['id'] for x in rec[:200]], handoff_ids=hand[:200]))
        active_ids = {r[0] for r in tx.execute("SELECT user_id FROM project_grants WHERE project_id=? AND active=1 AND roles_json!='[]'", (pid,))}
        if actor.configuration_admin:
            active_ids.add(str(actor.user_id))
        roles = effective_permissions(tx, actor, pid).roles
        page = MaterialControlPage(project_id=pid, project_version=p['version'], read_at=now.isoformat(), coverage_issues=issues,
            source_modes=source_modes(all_quantities), work_orders=work_orders, requirements=requirements, expedites=expedites,
            handoffs=handoffs, receipts=receipts, issue_marks=issue_marks, scope_total=len(scoped), problem_counts=problem_counts,
            material_task_counts={r[0]: r[1] for r in tx.execute("SELECT state,COUNT(*) FROM material_tasks WHERE project_id=? GROUP BY state", (pid,))}, total=total, limit=limit, offset=offset)

    ids = sorted({i[key] for row in page.requirements for i in row['issues'] for key in ('assignee_id', 'proposed_assignee_id') if i[key] and i[key] in active_ids})
    profiles = {}
    for start in range(0, len(ids), 50):
        try:
            profiles.update(service.member_profiles(actor, project_id, [UUID(uid) for uid in ids[start:start + 50]]))
        except DomainError:
            # A grant may be revoked between the projection and directory lookup.
            pass
    for row in page.requirements:
        for item in row['issues']:
            for prefix in ('assignee', 'proposed_assignee'):
                uid = item[prefix + '_id']
                if uid and uid in profiles:
                    item[prefix + '_name'] = profiles[uid]
            action = item['next_action']
            if action in ('arrange_iqc', 'trace') and (actor.read_only or not roles.intersection({'supply', 'project_owner'}) or p['mode'] != 'oem'):
                item['next_action'] = 'view_object'
            if action == 'confirm_time' and (actor.read_only or not roles.intersection({'supply', 'planner', 'project_owner'})):
                item['next_action'] = 'view_object'
    return page
