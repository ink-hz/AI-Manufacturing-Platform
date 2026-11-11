"""Task projections retain immutable collaboration history."""
import json
from .authority import register_reader
from .contracts import ObjectSummary, ObjectRelation
from .material_task_models import MaterialTask

def value(tx,pid,row):
    return MaterialTask(**json.loads(row['payload_json']), assignee_id=row['assignee_id'],proposed_assignee_id=row['proposed_assignee_id'],state=row['state'],history=[json.loads(r[0]) for r in tx.execute('SELECT payload_json FROM material_task_history WHERE project_id=? AND task_id=? ORDER BY seq',(str(pid),row['id']))],evidence_handoff_ids=[r[0] for r in tx.execute('SELECT handoff_id FROM material_task_evidence WHERE project_id=? AND task_id=? ORDER BY handoff_id',(str(pid),row['id']))])

def summary(tx,pid,row):
    item=value(tx,pid,row)
    return ObjectSummary(id=item.id,project_id=pid,kind='material_task',title=item.note,state=item.state,version=len(item.history),source=item.source,next_actions=(['material_task.accept','material_task.reassign','material_task.cancel'] if item.state=='pending' else ['material_task.progress','material_task.verify','material_task.close','material_task.reassign','material_task.cancel'] if item.state not in ('closed','cancelled') else []))

def relations(item,pid):
    return [ObjectRelation(relation='requirement',project_id=pid,kind='requirement',id=item.requirement_id)]
register_reader('material_task','material_tasks',MaterialTask,value,summary,relations)
