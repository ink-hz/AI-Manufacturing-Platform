"""Material coordination; proof is checked from current source facts."""
import json
from decimal import Decimal
from uuid import uuid4
from .authorization import effective_permissions, require_project
from .commands import COMMAND_REGISTRY
from .contracts import DomainError, MutationResult
from .laboratory import business, canonical
from .material_handoffs import actor_fact, applicable
from .material_task_models import (OpenMaterialTask, AcceptMaterialTask, ReassignMaterialTask,
    ProgressMaterialTask, VerifyMaterialTask, CloseMaterialTask, CancelMaterialTask)
from .orders import own
from .quality import fail

COORDINATORS = {'supply', 'project_owner'}
TRACE_ROLES = {'supply', 'project_owner', 'warehouse', 'production'}
ALL_ROLES = TRACE_ROLES | {'quality'}

def eligible(tx, actor, pid, uid, kind):
    if kind != 'verify' and actor.configuration_admin and str(actor.user_id) == str(uid):
        return True
    row = tx.execute('SELECT roles_json,qualifications_json FROM project_grants WHERE project_id=? AND user_id=? AND active=1', (str(pid),str(uid))).fetchone()
    if not row:
        return False
    roles, qualifications = set(json.loads(row[0])), set(json.loads(row[1]))
    return bool((kind == 'iqc' and 'quality' in roles and 'inspection' in qualifications) or (kind == 'trace' and roles & TRACE_ROLES) or (kind == 'verify' and roles & ALL_ROLES))

def assignees(service, actor, pid, kind):
    """Resolve eligible project members through the current host directory."""
    from uuid import UUID
    with service.store.transaction() as tx:
        require_project(tx, actor, pid)
        ids = [r[0] for r in tx.execute('SELECT user_id FROM project_grants WHERE project_id=? AND active=1 ORDER BY user_id', (str(pid),))
               if eligible(tx, actor, pid, r[0], kind)]
        if str(actor.user_id) not in ids and eligible(tx, actor, pid, actor.user_id, kind):
            ids.append(str(actor.user_id))
    items = []
    for start in range(0, len(ids), 50):
        chunk = ids[start:start+50]
        profiles = service.member_profiles(actor, pid, [UUID(i) for i in chunk])
        items.extend({'id': i, 'display_name': profiles[i]} for i in chunk if i in profiles and service.resolve_subject(UUID(i)))
    return items


def authorize(tx, actor, pid, command):
    if not command.action.startswith('material_task.'):
        return
    require_project(tx, actor, pid)
    if not applicable(tx, pid):
        fail('Material tasks require an OEM project', 422)
    roles = effective_permissions(tx, actor, pid).roles
    if command.action == 'material_task.open':
        if not roles & COORDINATORS: raise DomainError('FORBIDDEN',403,'Coordinator permission required')
        return
    row = own(tx, 'material_tasks', pid, command.task_id)
    if command.action in ('material_task.reassign','material_task.cancel'):
        allowed = bool(roles & COORDINATORS)
    elif command.action == 'material_task.accept':
        target = row['proposed_assignee_id'] or row['assignee_id']
        allowed = str(actor.user_id) == target and eligible(tx, actor, pid, target, row['task_kind'])
    else:
        allowed = str(actor.user_id) == row['assignee_id'] and eligible(tx, actor, pid, row['assignee_id'], row['task_kind'])
    if not allowed: raise DomainError('FORBIDDEN',403,'Current task responsibility permission denied')

def read_actions(tx, actor, pid, row):
    if actor.read_only or row['state'] in ('closed','cancelled'):
        return []
    result = []
    roles = effective_permissions(tx, actor, pid).roles
    if roles & COORDINATORS:
        result += ['material_task.reassign','material_task.cancel']
    if str(actor.user_id) == (row['proposed_assignee_id'] or row['assignee_id']) and eligible(tx, actor, pid, actor.user_id, row['task_kind']):
        if row['state'] == 'pending' or row['proposed_assignee_id']:
            result.append('material_task.accept')
    if str(actor.user_id) == row['assignee_id'] and row['state'] != 'pending' and eligible(tx, actor, pid, actor.user_id, row['task_kind']):
        result += ['material_task.progress','material_task.close']
        if row['task_kind'] != 'verify': result.append('material_task.verify')
    return result

def history(tx, context, ident, action, **fields):
    tx.execute('INSERT INTO material_task_history(project_id,task_id,payload_json) VALUES (?,?,?)',
               (str(context.project_id),str(ident),canonical(dict(action=action, **fields, **actor_fact(context)))))

def result(ident): return MutationResult(object_type='material_task', object_id=ident)

def receipt_context(tx, pid, receipt_id, req):
    receipt = own(tx, 'supply_receipts', pid, receipt_id)
    commitment = own(tx, 'supply_commitments', pid, receipt['commitment_id'])
    prior = own(tx, 'requirements', pid, commitment['requirement_id'])
    req = req if req is not None else prior
    lot = own(tx, 'material_lots', pid, receipt['material_lot_id'])
    if (any(prior[field] != req[field] for field in ('lineage_id','work_order_id','material_id','owner_id','unit','scale'))
            or any(lot[field] != req[field] for field in ('material_id','owner_id','unit','scale'))
            or receipt['unit'] != req['unit']):
        fail('Receipt does not belong to requirement', 422)
    return req


def open_scope(tx, c, cmd):
    from .material_task_references import resolve_reference
    req = own(tx, 'requirements', c.project_id, cmd.requirement_id) if cmd.requirement_id else None
    resolved = resolve_reference(tx, c.project_id, cmd.reference) if cmd.reference else None
    receipt_id, handoff_id = cmd.receipt_id, cmd.handoff_id
    if resolved:
        if cmd.task_kind not in resolved.task_kinds:
            fail('Reference does not support this task kind', 422)
        if cmd.task_kind == 'iqc':
            receipt_id = resolved.receipt_id
        if req is not None and resolved.work_order_id is not None and str(resolved.work_order_id) != req['work_order_id']:
            fail('Reference does not belong to contextual work order', 422)
    if cmd.task_kind == 'verify':
        if resolved is None: fail('Verification requires a reference', 422)
    elif cmd.task_kind == 'iqc':
        if not receipt_id or handoff_id: fail('IQC task requires one receipt', 422)
        req = receipt_context(tx, c.project_id, receipt_id, req)
    elif cmd.task_kind == 'trace':
        if req is None or not handoff_id or receipt_id or resolved: fail('Trace task requires a requirement and one handoff', 422)
        handoff = own(tx, 'material_handoffs', c.project_id, handoff_id)
        lot = own(tx, 'material_lots', c.project_id, handoff['material_lot_id'])
        if handoff['work_order_id'] != req['work_order_id'] or any(lot[f] != req[f] for f in ('material_id','owner_id','unit')):
            fail('Handoff does not belong to requirement', 422)
        if tx.execute('SELECT 1 FROM material_task_evidence WHERE project_id=? AND handoff_id=?', (str(c.project_id),str(handoff_id))).fetchone():
            fail('Handoff already allocated as evidence', 422)
    return req, resolved, str(receipt_id) if receipt_id else None, str(handoff_id) if handoff_id else None


def link_requirement(tx, pid, task_id, requirement_id):
    if requirement_id:
        tx.execute('INSERT OR IGNORE INTO material_task_requirements(project_id,task_id,requirement_id) VALUES (?,?,?)',
                   (str(pid), str(task_id), str(requirement_id)))


def open_task(tx, c, cmd):
    if not eligible(tx,c.actor,c.project_id,cmd.assignee_id,cmd.task_kind): fail('Assignee must be an eligible active project member',422)
    req, resolved, receipt_id, handoff_id = open_scope(tx, c, cmd)
    reference_key = resolved.scope_key if resolved else None
    requirement_id = req['id'] if req is not None else None
    existing = tx.execute("""SELECT id FROM material_tasks WHERE project_id=? AND task_kind=?
        AND state NOT IN ('closed','cancelled') AND
        (reference_key=? OR (?='iqc' AND receipt_id=?) OR (?='trace' AND handoff_id=?)) ORDER BY seq LIMIT 1""",
        (str(c.project_id),cmd.task_kind,reference_key,cmd.task_kind,receipt_id,cmd.task_kind,handoff_id)).fetchone()
    if existing:
        link_requirement(tx, c.project_id, existing['id'], requirement_id)
        history(tx,c,existing['id'],'reuse',note=cmd.note,requirement_id=requirement_id)
        return result(existing['id'])
    ident = str(uuid4()); now = c.now.isoformat()
    payload = dict(id=ident, requirement_id=requirement_id, task_kind=cmd.task_kind,
        receipt_id=receipt_id, handoff_id=handoff_id,
        note=cmd.note, opened_by=str(c.actor.user_id), recorded_at=now,
        source=dict(system='manual',object_type='material_task',external_id=ident,version=1,mode='manual',occurred_at=now,collected_at=now,evidence='Manual coordination task'))
    evidence = resolved.model_dump(mode='json', exclude={'requirement_id','task_kinds'}) if resolved else None
    tx.execute('INSERT INTO material_tasks(id,project_id,requirement_id,task_kind,receipt_id,handoff_id,assignee_id,state,payload_json,reference_json,reference_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (ident,str(c.project_id),requirement_id,cmd.task_kind,receipt_id,handoff_id,str(cmd.assignee_id),'pending',canonical(payload),canonical(evidence) if evidence else None,reference_key))
    link_requirement(tx, c.project_id, ident, requirement_id)
    history(tx,c,ident,'open',note=cmd.note,assignee_id=str(cmd.assignee_id)); return result(ident)

def active(tx,c,cmd):
    row = own(tx,'material_tasks',c.project_id,cmd.task_id)
    if row['state'] in ('closed','cancelled'): fail('Task is already finished')
    return row

def accept(tx,c,cmd):
    row=active(tx,c,cmd)
    if row['proposed_assignee_id']:
        tx.execute("UPDATE material_tasks SET assignee_id=proposed_assignee_id,proposed_assignee_id=NULL,state='processing' WHERE id=?",(row['id'],))
    elif row['state']=='pending': tx.execute("UPDATE material_tasks SET state='processing' WHERE id=?",(row['id'],))
    else: fail('Task is already accepted')
    history(tx,c,row['id'],'accept'); return result(row['id'])

def reassign(tx,c,cmd):
    row=active(tx,c,cmd)
    if str(cmd.assignee_id)==row['assignee_id'] or not eligible(tx,c.actor,c.project_id,cmd.assignee_id,row['task_kind']): fail('New assignee must be a different eligible member',422)
    tx.execute('UPDATE material_tasks SET proposed_assignee_id=? WHERE id=?',(str(cmd.assignee_id),row['id']))
    history(tx,c,row['id'],'reassign',assignee_id=str(cmd.assignee_id),reason=cmd.reason); return result(row['id'])

def progress(tx,c,cmd):
    row=active(tx,c,cmd)
    if row['state']=='pending': fail('Task must be accepted')
    if row['task_kind']=='verify' and (cmd.found_quantity is not None or cmd.found_location is not None):
        fail('Verification does not record found quantity or location proof',422)
    data=business(cmd); data.pop('task_id',None)
    tx.execute("UPDATE material_tasks SET state='processing' WHERE id=?",(row['id'],))
    history(tx,c,row['id'],'progress',**data); return result(row['id'])

def proof(tx,pid,row):
    if row['task_kind']=='iqc':
        r=tx.execute('SELECT q_atoms FROM effective_supply_receipts WHERE project_id=? AND id=?',(str(pid),row['receipt_id'])).fetchone()
        inspected=tx.execute('SELECT COALESCE(SUM(accepted_atoms+rejected_atoms),0) FROM effective_iqc_results WHERE project_id=? AND receipt_id=?',(str(pid),row['receipt_id'])).fetchone()[0]
        return bool(r and r[0]>0 and inspected>=r[0])
    original=own(tx,'material_handoffs',pid,row['handoff_id']); origin=json.loads(original['payload_json'])
    if not original['receipt_json']: return False
    receipt = json.loads(original['receipt_json'])
    if receipt['received_location'] != origin['to_location']: return False
    total=Decimal(receipt['received_quantity'])
    for e in tx.execute('SELECT h.* FROM material_task_evidence e JOIN material_handoffs h ON h.id=e.handoff_id AND h.project_id=e.project_id WHERE e.project_id=? AND e.task_id=?',(str(pid),row['id'])):
        if not e['receipt_json']: return False
        total += Decimal(json.loads(e['receipt_json'])['received_quantity'])
    return total>=Decimal(origin['quantity'])

def verify(tx,c,cmd):
    row=active(tx,c,cmd)
    if row['task_kind']=='verify': fail('Identity verification closes directly with a conclusion',422)
    if row['state']=='pending': fail('Task must be accepted')
    link_evidence(tx,c,row,cmd.handoff_ids)
    if not proof(tx,c.project_id,row): fail('Current source evidence does not complete the task')
    tx.execute("UPDATE material_tasks SET state='verification' WHERE id=?",(row['id'],))
    history(tx,c,row['id'],'verify',evidence=cmd.evidence,handoff_ids=[str(i) for i in cmd.handoff_ids]); return result(row['id'])

def link_evidence(tx,c,row,handoff_ids):
    if row['task_kind']=='iqc' and handoff_ids: fail('IQC does not use handoff evidence',422)
    if row['task_kind']=='trace':
        origin=own(tx,'material_handoffs',c.project_id,row['handoff_id']); op=json.loads(origin['payload_json'])
        for ident in handoff_ids:
            h=own(tx,'material_handoffs',c.project_id,ident); p=json.loads(h['payload_json'])
            existing=tx.execute('SELECT task_id FROM material_task_evidence WHERE project_id=? AND handoff_id=?',(str(c.project_id),str(ident))).fetchone()
            used_as_scope=tx.execute("SELECT 1 FROM material_tasks WHERE project_id=? AND handoff_id=? AND id<>?", (str(c.project_id),str(ident),row['id'])).fetchone()
            if used_as_scope or str(ident)==row['handoff_id'] or not h['receipt_json'] or h['material_lot_id']!=origin['material_lot_id'] or h['work_order_id']!=origin['work_order_id'] or h['receiver_id']!=origin['receiver_id'] or p['unit']!=op['unit'] or json.loads(h['receipt_json'])['received_location']!=op['to_location'] or (existing and existing[0]!=row['id']):
                fail('Incompatible or allocated signed handoff evidence',422)
            tx.execute('INSERT OR IGNORE INTO material_task_evidence(project_id,task_id,handoff_id) VALUES (?,?,?)',(str(c.project_id),row['id'],str(ident)))

def close(tx,c,cmd):
    row=active(tx,c,cmd)
    if row['state']=='pending': fail('Task must be accepted')
    resolved = {}
    if row['task_kind']=='verify':
        from .material_verification import close_evidence
        resolved = close_evidence(tx,c.project_id,row,cmd)
    else:
        if cmd.outcome not in {'fulfilled','discrepancy','false_alarm','superseded'} or cmd.resolved_reference is not None:
            fail('IQC and trace require quantity proof and legacy conclusions',422)
        link_evidence(tx,c,row,cmd.handoff_ids)
        if not proof(tx,c.project_id,row): fail('Current source evidence does not complete the task')
    tx.execute("UPDATE material_tasks SET state='closed',closure_json=? WHERE id=?",(canonical(dict(outcome=cmd.outcome,evidence=cmd.evidence,**resolved,**actor_fact(c))),row['id']))
    history(tx,c,row['id'],'close',outcome=cmd.outcome,evidence=cmd.evidence,handoff_ids=[str(i) for i in cmd.handoff_ids],
            **({'resolved_reference':resolved['resolved_reference']} if resolved else {}))
    return result(row['id'])

def cancel(tx,c,cmd):
    row=active(tx,c,cmd); tx.execute("UPDATE material_tasks SET state='cancelled' WHERE id=?",(row['id'],))
    history(tx,c,row['id'],'cancel',reason=cmd.reason); return result(row['id'])

for model, handler, roles in [(OpenMaterialTask,open_task,COORDINATORS),(AcceptMaterialTask,accept,ALL_ROLES),(ReassignMaterialTask,reassign,COORDINATORS),(ProgressMaterialTask,progress,ALL_ROLES),(VerifyMaterialTask,verify,ALL_ROLES),(CloseMaterialTask,close,ALL_ROLES),(CancelMaterialTask,cancel,COORDINATORS)]:
    COMMAND_REGISTRY.register(model,roles=roles,qualifications=set(),handler=handler)
