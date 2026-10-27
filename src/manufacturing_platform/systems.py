"""System inventory and one active authority per line and business object."""
from .collaboration_store import CollaborationStore, require
from .repository import Conflict


class SystemService(CollaborationStore):
    def system(self, request, actor_id, actor, system_id=None):
        def change(db):
            if system_id:
                previous = self.object(db,'systems',system_id)
                self.cas(previous,request)
                value = self.changed({**previous,**self.fields(request,patch=True)},actor)
            else:
                value = self.new(self.fields(request),actor)
            require(len(value['line_ids']) == len(set(value['line_ids'])), 'Duplicate business lines')
            for line in value['line_ids']:
                self.catalog.line(line)
            self.persist(db,'systems',value)
            # Explicitly retire conflicting current agreements, keeping their prior audit.
            for authority in self.rows(db,'authorities'):
                if authority['system_id'] == value['id'] and authority['active'] and (not value['active'] or authority['line_id'] not in value['line_ids']):
                    authority = self.changed({**authority,'active':False},actor)
                    self.persist(db,'authorities',authority)
                    self.event(db,'authorities',authority,'retire',actor_id,actor,request.operation_id,reason='Source system retired or business scope removed')
            self.event(db,'systems',value,'update' if system_id else 'create',actor_id,actor,request.operation_id)
            return value
        return self.transact(request,actor_id,actor,'system',system_id or '',change)

    def authority(self, request, actor_id, actor, authority_id=None):
        def change(db):
            if authority_id:
                previous = self.object(db,'authorities',authority_id)
                self.cas(previous,request)
                value = self.changed({**previous,**self.fields(request,patch=True)},actor)
            else:
                value = self.new(self.fields(request),actor)
            self.catalog.line(value['line_id'])
            self.reference(db,value['system_id'],line_id=value['line_id'] if value['active'] else None,active=value['active'])
            if value['active'] and db.execute('SELECT 1 FROM manufacturing_authorities WHERE line_id=? AND object_type=? AND active=1 AND id!=?',(value['line_id'],value['object_type'],value['id'])).fetchone():
                raise Conflict()
            self.persist(db,'authorities',value)
            self.event(db,'authorities',value,'update' if authority_id else 'create',actor_id,actor,request.operation_id)
            return value
        return self.transact(request,actor_id,actor,'authority',authority_id or '',change)
