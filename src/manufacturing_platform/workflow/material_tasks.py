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
    if actor.configuration_admin and str(actor.user_id) == str(uid):
        return True
    row = tx.execute('SELECT roles_json,qualifications_json FROM project_grants WHERE project_id=? AND user_id=? AND active=1', (str(pid),str(uid))).fetchone()
    if not row:
        return False
    roles, qualifications = set(json.loads(row[0])), set(json.loads(row[1]))
    return bool((kind == 'iqc' and 'quality' in roles and 'inspection' in qualifications) or (kind == 'trace' and roles & TRACE_ROLES))

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
        result += ['material_task.progress','material_task.verify','material_task.close']
    return result

def history(tx, context, ident, action, **fields):
    tx.execute('INSERT INTO material_task_history(project_id,task_id,payload_json) VALUES (?,?,?)',
               (str(context.project_id),str(ident),canonical(dict(action=action, **fields, **actor_fact(context)))))

def result(ident): return MutationResult(object_type='material_task', object_id=ident)

def open_task(tx, c, cmd):
    req = own(tx,'requirements',c.project_id,cmd.requirement_id)
    if not eligible(tx,c.actor,c.project_id,cmd.assignee_id,cmd.task_kind): fail('Assignee must be an eligible active project member',422)
    if cmd.task_kind == 'iqc':
        if not cmd.receipt_id or cmd.handoff_id: fail('IQC task requires one receipt',422)
        receipt = own(tx,'supply_receipts',c.project_id,cmd.receipt_id)
        commitment = own(tx,'supply_commitments',c.project_id,receipt['commitment_id'])
        prior = own(tx,'requirements',c.project_id,commitment['requirement_id'])
        lot = own(tx,'material_lots',c.project_id,receipt['material_lot_id'])
        fields = ('lineage_id', 'work_order_id', 'material_id', 'owner_id', 'unit')
        if (any(prior[field] != req[field] for field in fields)
                or any(lot[field] != req[field] for field in ('material_id', 'owner_id', 'unit'))
                or receipt['unit'] != req['unit']):
            fail('Receipt does not belong to requirement',422)
        scope, ident_field = 'receipt_id', str(cmd.receipt_id)
    else:
        if not cmd.handoff_id or cmd.receipt_id: fail('Trace task requires one handoff',422)
        handoff = own(tx,'material_handoffs',c.project_id,cmd.handoff_id)
        lot = own(tx,'material_lots',c.project_id,handoff['material_lot_id'])
        if handoff['work_order_id'] != req['work_order_id'] or lot['material_id'] != req['material_id'] or lot['owner_id'] != req['owner_id'] or lot['unit'] != req['unit']:
            fail('Handoff does not belong to requirement',422)
        if tx.execute('SELECT 1 FROM material_task_evidence WHERE project_id=? AND handoff_id=?', (str(c.project_id),str(cmd.handoff_id))).fetchone(): fail('Handoff already allocated as evidence',422)
        scope, ident_field = 'handoff_id', str(cmd.handoff_id)
    if tx.execute(f"SELECT 1 FROM material_tasks WHERE project_id=? AND {scope}=? AND state NOT IN ('closed','cancelled')",(str(c.project_id),ident_field)).fetchone(): fail('Task already exists for this scope')
    ident = str(uuid4()); now = c.now.isoformat()
    payload = dict(id=ident, requirement_id=str(cmd.requirement_id), task_kind=cmd.task_kind,
        receipt_id=str(cmd.receipt_id) if cmd.receipt_id else None, handoff_id=str(cmd.handoff_id) if cmd.handoff_id else None,
        note=cmd.note, opened_by=str(c.actor.user_id), recorded_at=now,
        source=dict(system='manual',object_type='material_task',external_id=ident,version=1,mode='manual',occurred_at=now,collected_at=now,evidence='Manual coordination task'))
    tx.execute('INSERT INTO material_tasks(id,project_id,requirement_id,task_kind,receipt_id,handoff_id,assignee_id,state,payload_json) VALUES (?,?,?,?,?,?,?,?,?)',
        (ident,str(c.project_id),str(cmd.requirement_id),cmd.task_kind,payload['receipt_id'],payload['handoff_id'],str(cmd.assignee_id),'pending',canonical(payload)))
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
    link_evidence(tx,c,row,cmd.handoff_ids)
    if not proof(tx,c.project_id,row): fail('Current source evidence does not complete the task')
    tx.execute("UPDATE material_tasks SET state='closed',closure_json=? WHERE id=?",(canonical(dict(outcome=cmd.outcome,evidence=cmd.evidence,**actor_fact(c))),row['id']))
    history(tx,c,row['id'],'close',outcome=cmd.outcome,evidence=cmd.evidence,handoff_ids=[str(i) for i in cmd.handoff_ids]); return result(row['id'])

def cancel(tx,c,cmd):
    row=active(tx,c,cmd); tx.execute("UPDATE material_tasks SET state='cancelled' WHERE id=?",(row['id'],))
    history(tx,c,row['id'],'cancel',reason=cmd.reason); return result(row['id'])

for model, handler, roles in [(OpenMaterialTask,open_task,COORDINATORS),(AcceptMaterialTask,accept,ALL_ROLES),(ReassignMaterialTask,reassign,COORDINATORS),(ProgressMaterialTask,progress,ALL_ROLES),(VerifyMaterialTask,verify,ALL_ROLES),(CloseMaterialTask,close,ALL_ROLES),(CancelMaterialTask,cancel,COORDINATORS)]:
    COMMAND_REGISTRY.register(model,roles=roles,qualifications=set(),handler=handler)
