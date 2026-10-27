"""Frozen engineering snapshots and independent manual handoff receipts."""
from uuid import uuid4
from .collaboration_store import CollaborationStore, require
from .repository import Conflict


class EngineeringService(CollaborationStore):
    def validate_package(self, db, value, line_id, *, verify=False):
        for item in value['items']:
            self.reference(db,item['source_system_id'],line_id=line_id)
            require(item['status'] != 'na' or bool(item['reason']), 'Not applicable items require a reason')
            if verify:
                require(item['status'] in {'verified','na'}, 'All applicable items must be reviewed')
                if item['status'] == 'verified':
                    require(all(item[k] for k in ('source_name','source_ref','revision','evidence','owner')), 'Reviewed items require source, revision, evidence and owner')
        if verify:
            require(all(value[k] for k in ('product_ref','scope','owner')), 'Package requires product, scope and owner')
            if line_id == 'oem':
                require(all(value[k] for k in ('customer_version','internal_version','approval_party')), 'OEM requires separate versions and approval responsibility')
        if value['approval_status'] == 'confirmed':
            require(bool(value['approval_evidence']) and bool(value['approval_party']), 'External approval requires responsible party and evidence')

    def package(self, project_id, request, actor_id, actor, package_id=None):
        def change(db):
            project = self._read(db,project_id)['project']
            if package_id:
                old = self.object(db,'packages',package_id,project_id)
                self.cas(old,request)
                require(old['status'] in {'draft','returned'}, 'Frozen or submitted package cannot be edited')
                value = self.changed({**old,**self.fields(request)},actor)
            else:
                value = self.new(self.fields(request),actor)
                value.update(project_id=project_id,family_id=str(uuid4()),revision=1,supersedes_id=None,status='draft',reason='')
            self.validate_package(db,value,project['line_id'])
            self.persist(db,'packages',value)
            self.event(db,'packages',value,'update' if package_id else 'create',actor_id,actor,request.operation_id)
            return value
        return self.transact(request,actor_id,actor,'package',project_id+'/'+(package_id or ''),change)

    def package_action(self, project_id, package_id, request, actor_id, actor):
        def change(db):
            project = self._read(db,project_id)['project']
            old = self.object(db,'packages',package_id,project_id)
            self.cas(old,request)
            action = request.action
            allowed = {'submit':{'draft','returned'},'verify':{'review'},'return':{'review'},'revise':{'verified','invalid'},'invalidate':{'verified'}}
            require(old['status'] in allowed[action], 'Invalid package transition')
            require(action not in {'return','invalidate'} or bool(request.reason), 'Reason is required')
            if action == 'verify':
                self.validate_package(db,old,project['line_id'],verify=True)
            if action == 'revise':
                # Repeated revise with a different operation must never create parallel revision N+1.
                if db.execute('SELECT 1 FROM manufacturing_packages WHERE family_id=? AND revision>?',(old['family_id'],old['revision'])).fetchone():
                    raise Conflict()
                value = self.new(self.fields_from_package(old),actor)
                value.update(project_id=project_id,family_id=old['family_id'],revision=old['revision']+1,supersedes_id=old['id'],status='draft',reason='')
                if value['approval_status'] == 'confirmed':
                    value.update(approval_status='unknown', approval_evidence='')
                for item in value['items']:
                    if item['status'] == 'verified':
                        item['status'] = 'pending'
            else:
                statuses = {'submit':'review','verify':'verified','return':'returned','invalidate':'invalid'}
                value = self.changed({**old,'status':statuses[action],'reason':request.reason},actor)
            self.persist(db,'packages',value)
            self.event(db,'packages',value,action,actor_id,actor,request.operation_id,reason=request.reason)
            if action == 'invalidate':
                for record in self.rows(db,'readiness',project_id):
                    if record['package_id'] != package_id:
                        continue
                    # A withdrawn execution basis affects every assertion of applicability.
                    for item in record['items']:
                        item.update(status='pending',reason='Package invalidated: '+request.reason)
                    record = self.changed({**record,'status':'pending'},actor)
                    self.persist(db,'readiness',record)
                    self.event(db,'readiness',record,'basis_invalidated',actor_id,actor,request.operation_id,reason=request.reason)
            return value
        return self.transact(request,actor_id,actor,'package_action',project_id+'/'+package_id,change)

    @staticmethod
    def fields_from_package(value):
        from .collaboration_models import PackageFields
        from copy import deepcopy
        return deepcopy({k:value[k] for k in PackageFields.model_fields})

    def handoff(self, project_id, request, actor_id, actor):
        def create(db):
            project = self._read(db,project_id)['project']
            package = self.object(db,'packages',request.package_id,project_id)
            require(package['status']=='verified', 'Handoff requires a fixed verified package')
            self.reference(db,request.to_system_id,line_id=project['line_id'],active=True)
            value = self.new(self.fields(request),actor)
            value.update(project_id=project_id,package_revision=package['revision'],status='draft',received_revision=None,reason='')
            value['code'] = 'HO-'+value['id'].upper()
            self.persist(db,'handoffs',value)
            self.event(db,'handoffs',value,'create',actor_id,actor,request.operation_id)
            return value
        return self.transact(request,actor_id,actor,'handoff',project_id,create)

    def handoff_action(self, project_id, handoff_id, request, actor_id, actor):
        def change(db):
            self._read(db,project_id)
            old = self.object(db,'handoffs',handoff_id,project_id)
            self.cas(old,request)
            package = self.object(db,'packages',old['package_id'],project_id)
            allowed = {'send':{'draft'},'receive':{'sent'},'return':{'sent'},'cancel':{'draft','sent'}}
            require(old['status'] in allowed[request.action], 'Invalid handoff transition; corrections require a new record')
            if request.action in {'send','receive'}:
                require(package['status']=='verified', 'Package is no longer valid for handoff')
                require(bool(request.evidence) and request.occurred_at is not None, 'Manual registration requires evidence and external event time')
            if request.action == 'receive':
                require(request.received_revision == old['package_revision'], 'Received package revision does not match')
                require(bool(actor_id), 'Receipt requires authenticated actor')
            require(request.action != 'return' or bool(request.reason), 'Return requires a reason')
            fields = self.fields(request)
            fields.pop('action')
            value = self.changed({**old,**fields,'status':{'send':'sent','receive':'received','return':'returned','cancel':'cancelled'}[request.action]},actor)
            self.persist(db,'handoffs',value)
            self.event(db,'handoffs',value,request.action,actor_id,actor,request.operation_id,reason=request.reason)
            return value
        return self.transact(request,actor_id,actor,'handoff_action',project_id+'/'+handoff_id,change)
