"""Fixed-scope production readiness with evidence rules and linked issues."""
from uuid import uuid4
from .collaboration_store import CollaborationStore, require
from .repository import Conflict, NotFound, _now


def readiness_status(items, package_status):
    required = [item for item in items if item['required']]
    if any(item['status']=='blocked' for item in required):
        return 'blocked'
    if package_status == 'verified' and required and all(item['status'] in {'verified','na'} for item in required):
        return 'complete'
    return 'pending'


def item_stage(item):
    return 'S4' if item['kind'] in {'materials','customer_material','equipment','people'} else 'S5'


class ReadinessService(CollaborationStore):
    def validate_items(self, db, value, package, project):
        package_items = {item['id']:item for item in package['items']}
        for item in value['items']:
            self.reference(db,item['source_system_id'],line_id=project['line_id'])
            if item['package_item_id'] is not None and item['package_item_id'] not in package_items:
                raise NotFound()
            require(item['status'] not in {'blocked','na'} or bool(item['reason']), 'Blocked and not applicable items require a reason')
            if item['kind']=='version' and item['status']!='na':
                reference = package_items.get(item['package_item_id'])
                require(reference is not None and reference['status']=='verified', 'Version check must reference applicable verified package item')
            if item['status'] != 'verified':
                continue
            require(all(item[k] for k in ('owner','source_ref','evidence')), 'Verified checks require owner, source and evidence')
            if item['kind'] == 'equipment':
                require(item['valid_until'] is not None and item['valid_until'] >= value['planned_use_date'], 'Equipment validity must cover planned use date')
            if item['kind'] == 'version':
                require(package['status']=='verified', 'Version check requires a verified package')
            if item['kind'] == 'first_article' and item['required']:
                require(item['first_article_result']=='passed', 'Required first article must have passed')
            if item['kind'] in {'materials','customer_material'}:
                require(item['supply_mode']!='unknown', 'Material supply ownership must be explicit')
            if item['kind'] == 'customer_material':
                require(item['supply_mode'] in {'customer','mixed'}, 'Customer material requires customer or mixed ownership')
            if item['kind']=='customer' and item['required'] and project['line_id']=='oem':
                require(package['approval_status']=='confirmed' and bool(package['approval_evidence']) and bool(package['approval_party']), 'OEM customer approval requires external approval evidence')

    def readiness(self, project_id, request, actor_id, actor, readiness_id=None):
        def change(db):
            project = self._read(db,project_id)['project']
            if readiness_id:
                old = self.object(db,'readiness',readiness_id,project_id)
                self.cas(old,request)
                if old.get('superseded_by'):
                    raise Conflict()
                items = self.fields(request)['items']
                fixed = lambda rows: {item['id']:(item['kind'],item['required'],item['package_item_id']) for item in rows}
                require(fixed(items)==fixed(old['items']), 'Readiness item selection and applicability are frozen')
                value = self.changed({**old,'items':items},actor)
            else:
                value = self.new(self.fields(request),actor)
                value.update(project_id=project_id,superseded_by=None)
                require(not value['required'] or any(item['required'] for item in value['items']),
                        'Required readiness needs at least one required item')
            package = self.object(db,'packages',value['package_id'],project_id)
            if not readiness_id:
                require(package['status']=='verified', 'Readiness requires a fixed verified package')
            value['package_revision'] = package['revision']
            self.validate_items(db,value,package,project)
            value['status'] = readiness_status(value['items'],package['status'])
            if not readiness_id and request.supersedes_id is not None:
                self.supersede(db,project_id,request,value,package,actor_id,actor)
            self.persist(db,'readiness',value)
            self.event(db,'readiness',value,'update' if readiness_id else 'create',actor_id,actor,request.operation_id)
            return value
        return self.transact(request,actor_id,actor,'readiness',project_id+'/'+(readiness_id or ''),change)

    def supersede(self, db, project_id, request, value, package, actor_id, actor):
        old = self.object(db,'readiness',request.supersedes_id,project_id)
        if old['version'] != request.supersedes_version or old.get('superseded_by'):
            raise Conflict()
        require(all(old[key] == value[key] for key in ('work_order_ref','scope','required')),
                'Replacement must preserve work order, scope and required applicability')
        previous_package = self.object(db,'packages',old['package_id'],project_id)
        require(package['family_id'] == previous_package['family_id'] and package['revision'] > previous_package['revision'],
                'Replacement requires a strictly newer revision in the same package family')
        items = {item['id']:item for item in value['items']}
        require(all(item['id'] in items and items[item['id']]['kind'] == item['kind'] and items[item['id']]['required']
                    for item in old['items'] if item['required']),
                'Replacement must preserve every required check ID, kind and applicability')
        require(all(item['status']=='pending' or
                    (item['status']=='na' and all(item[key] for key in ('owner','source_ref','evidence','reason')))
                    for item in value['items']),
                'Replacement checks require pending status or a documented independent NA review')
        historical = self.changed({**old,'superseded_by':value['id']},actor)
        self.persist(db,'readiness',historical)
        self.event(db,'readiness',historical,'supersede',actor_id,actor,request.operation_id,
                   reason='Replaced by '+value['id']+' for package revision '+str(package['revision']))

    def issue(self, project_id, readiness_id, request, actor_id, actor):
        def create(db):
            detail = self._read(db,project_id)
            readiness = self.object(db,'readiness',readiness_id,project_id)
            if readiness.get('superseded_by'):
                raise Conflict()
            item = next((item for item in readiness['items'] if item['id']==request.item_id),None)
            if item is None:
                raise NotFound()
            require(item['status'] in {'pending','blocked'}, 'Issues must reference an unresolved check')
            now = _now()
            fields = self.fields(request)
            fields.pop('item_id')
            task = {**fields,'id':str(uuid4()),'project_id':project_id,'stage_id':item_stage(item),'kind':'issue','status':'todo',
                    'version':1,'created_at':now,'updated_at':now,'updated_by':actor,
                    'source':{'type':'readiness','id':readiness_id,'item_id':item['id']}}
            detail['tasks'].append(task)
            self._activity(detail,actor,'task_created','从准备缺项创建问题',stage_id=task['stage_id'],task_id=task['id'])
            self._save(db,detail)
            self.event(db,'readiness',readiness,'issue_created',actor_id,actor,request.operation_id,reason=task['id'])
            return task
        return self.transact(request,actor_id,actor,'readiness_issue',project_id+'/'+readiness_id,create)
