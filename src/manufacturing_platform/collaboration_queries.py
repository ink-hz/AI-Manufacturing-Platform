"""One query composition for project completion, controls and dashboard attention."""
import json
from .readiness import item_stage


def compose_status(db, project_id, status):
    if status == 'archived':
        return status
    rows = [json.loads(row[0]) for row in db.execute('SELECT body FROM manufacturing_readiness WHERE project_id=?',(project_id,))]
    required = [row for row in rows if row['required'] and not row.get('superseded_by')]
    if any(row['status']=='blocked' for row in required):
        return 'blocked'
    if status == 'completed' and any(row['status']!='complete' for row in required):
        return 'active'
    return status


def attention(db):
    projects = {row[0]:json.loads(row[1])['project'] for row in db.execute('SELECT id,body FROM manufacturing_projects')}
    result = []
    def add(kind, record, title, reason, item=None):
        project = projects.get(record['project_id'])
        if not project or project['archived']:
            return
        result.append({'project_id':project['id'],'project_name':project['name'],
                       'stage_id':item_stage(item) if kind=='readiness' and item else 'S5' if kind=='readiness' else 'S2',
                       'object_type':kind,'object_id':record['id'],'item_id':item['id'] if item else None,
                       'title':title,'reason':reason,'owner':item['owner'] if item else record['owner'],
                       'due_date':item.get('due_date') if item else record.get('due_date')})
    for row in db.execute('SELECT body FROM manufacturing_packages ORDER BY rowid'):
        package = json.loads(row[0])
        if package['status'] in {'verified','invalid'}:
            continue
        pending = [item for item in package['items'] if item['status']=='pending']
        if pending:
            for item in pending:
                add('package',package,item['title'],'Engineering material requires review',item)
        else:
            add('package',package,package['title'],package['reason'] or 'Package awaits manual verification')
    for row in db.execute('SELECT body FROM manufacturing_handoffs ORDER BY rowid'):
        handoff = json.loads(row[0])
        if handoff['status'] in {'draft','sent','returned'}:
            add('handoff',handoff,handoff['to_party'],handoff['reason'] or ('Awaiting manual receipt' if handoff['status']=='sent' else 'Handoff '+handoff['status']))
    for row in db.execute('SELECT body FROM manufacturing_readiness ORDER BY rowid'):
        record = json.loads(row[0])
        if record.get('superseded_by'):
            continue
        pending = [item for item in record['items'] if item['required'] and item['status'] in {'pending','blocked'}]
        for item in pending:
            add('readiness',record,item['label'],item['reason'] or 'Readiness requires evidence',item)
        if record['required'] and record['status']!='complete' and not pending:
            add('readiness',record,record['title'],'Execution basis is not verified')
    return result
