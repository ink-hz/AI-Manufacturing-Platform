"""Task projections retain immutable collaboration history."""
import json
from .authority import register_reader
from .contracts import ObjectSummary, ObjectRelation
from .material_task_models import MaterialTask

def value(tx, pid, row):
    from .material_task_reference_models import TaskReferenceEvidence
    from .material_task_references import reference_status
    evidence = TaskReferenceEvidence.model_validate_json(row['reference_json']) if row['reference_json'] else None
    current, current_ref, issue = reference_status(tx, pid, evidence) if evidence else (None, None, None)
    payload = json.loads(row['payload_json'])
    for key in ('reference', 'closure', 'context_requirement_ids', 'reference_pinned', 'reference_current', 'current_reference', 'reference_issue'):
        payload.pop(key, None)
    return MaterialTask(**payload, assignee_id=row['assignee_id'],
        proposed_assignee_id=row['proposed_assignee_id'], state=row['state'],
        history=[json.loads(r[0]) for r in tx.execute('SELECT payload_json FROM material_task_history WHERE project_id=? AND task_id=? ORDER BY seq', (str(pid), row['id']))],
        evidence_handoff_ids=[r[0] for r in tx.execute('SELECT handoff_id FROM material_task_evidence WHERE project_id=? AND task_id=? ORDER BY handoff_id', (str(pid), row['id']))],
        reference=evidence, closure=json.loads(row['closure_json']) if row['closure_json'] else None,
        context_requirement_ids=sorted({r[0] for r in tx.execute('SELECT requirement_id FROM material_task_requirements WHERE project_id=? AND task_id=?', (str(pid), row['id']))} | ({row['requirement_id']} if row['requirement_id'] else set())),
        reference_pinned=evidence is not None, reference_current=current, current_reference=current_ref, reference_issue=issue)

def summary(tx,pid,row):
    payload = json.loads(row['payload_json'])
    version = tx.execute(
        'SELECT COUNT(*) FROM material_task_history WHERE project_id=? AND task_id=?',
        (str(pid), row['id']),
    ).fetchone()[0]
    state = row['state']
    return ObjectSummary(
        id=row['id'], project_id=pid, kind='material_task', title=payload['note'],
        state=state, version=version, source=payload['source'],
        assignee_id=row['assignee_id'], proposed_assignee_id=row['proposed_assignee_id'],
        next_actions=(['material_task.accept', 'material_task.reassign', 'material_task.cancel']
                      if state == 'pending' else
                      ['material_task.progress', *(['material_task.verify'] if row['task_kind'] != 'verify' else []), 'material_task.close',
                       'material_task.reassign', 'material_task.cancel']
                      if state not in ('closed', 'cancelled') else []),
    )

def relations(item,pid):
    return [ObjectRelation(relation='requirement',project_id=pid,kind='requirement',id=ident) for ident in item.context_requirement_ids]
register_reader('material_task','material_tasks',MaterialTask,value,summary,relations)
