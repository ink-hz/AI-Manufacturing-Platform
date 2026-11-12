import json
import re
import sqlite3
import unicodedata
from uuid import uuid4

from .authorization import require_project
from .commands import COMMAND_REGISTRY
from .contracts import DomainError, MutationResult
from .native_material_models import BindMesOrder, RefreshMesOrder


def can_manage(tx, actor, project_id):
    row = tx.execute('SELECT roles_json FROM project_grants WHERE project_id=? AND user_id=? AND active=1', (str(project_id), str(actor.user_id))).fetchone()
    return bool(actor.configuration_admin and not actor.read_only and row and {'project_owner', 'engineering'} & set(json.loads(row[0])))


def authorize(tx, actor, project_id, command, resolve_subject):
    require_project(tx, actor, project_id)
    if not can_manage(tx, actor, project_id) or not resolve_subject(actor.user_id):
        raise DomainError('FORBIDDEN', 403, 'MES association permission denied')
    if not tx.execute('SELECT 1 FROM work_orders WHERE id=? AND project_id=?', (str(command.work_order_id), str(project_id))).fetchone():
        raise DomainError('NOT_FOUND', 404, 'Work order not found')


def current(tx, command):
    return tx.execute('SELECT * FROM mes_order_bindings WHERE work_order_id=? AND active=1', (str(command.work_order_id),)).fetchone()


def validate_binding(tx, command):
    row = current(tx, command)
    if isinstance(command, BindMesOrder):
        if row:
            if str(command.replace_binding_id) != row['id'] or not command.reason or not command.reason.strip():
                raise DomainError('MES_REPLACEMENT_REQUIRED', 409, 'Specify current binding and replacement reason')
        elif command.replace_binding_id is not None or command.reason is not None:
            raise DomainError('MES_BINDING_CONFLICT', 409, 'Binding changed')
    elif not row or row['id'] != str(command.binding_id):
        raise DomainError('MES_BINDING_CONFLICT', 409, 'Binding changed')
    return row


def apply(tx, context, command, observation):
    row = validate_binding(tx, command)
    now = context.now.isoformat()
    if isinstance(command, BindMesOrder):
        ident = str(uuid4())
        if row:
            tx.execute('UPDATE mes_order_bindings SET active=0 WHERE id=?', (row['id'],))
        try:
            tx.execute('INSERT INTO mes_order_bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (ident, str(context.project_id), str(command.work_order_id), observation['namespace'], command.shop_order, observation['environment'], observation['site_code'], now, str(context.actor.user_id), json.dumps(observation['request_ids']), 1, None, command.reason))
        except sqlite3.IntegrityError:
            raise DomainError('MES_BINDING_CONFLICT', 409, 'MES order is already associated') from None
        if row:
            tx.execute('UPDATE mes_order_bindings SET superseded_by=?,reason=? WHERE id=?', (ident, command.reason, row['id']))
    else:
        ident = row['id']
        if observation['namespace'] != row['namespace']:
            raise DomainError('MES_SOURCE_CHANGED', 409, 'MES source changed; replace association')
    snapshot = str(uuid4())
    tx.execute('INSERT INTO mes_material_snapshots VALUES (?,?,?,?,?)', (snapshot, ident, now, observation['total'], json.dumps(observation['request_ids'])))
    for position, item in enumerate(observation['components']):
        tx.execute('INSERT INTO mes_material_components VALUES (?,?,?,?,?,?,?,?)', (snapshot, position, item['component_key'], item['material_id'], item['required_quantity'], item['withdrawn_quantity'], item['unit'], item['storage_location']))
    return MutationResult(object_type='work_order', object_id=command.work_order_id)


def plain_quantity(value):
    """Project accepted MES numbers exactly, without unbounded exponent expansion."""
    if value is None:
        return None, True
    match = re.fullmatch(r'(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?', value)
    if not match:
        return None, False
    mantissa, exponent = match.groups()
    mantissa = ''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in mantissa)
    if exponent is None:
        return mantissa, True
    whole, _, fraction = mantissa.partition('.')
    digits = whole + fraction
    point = len(whole) + int(exponent)
    length = max(point, len(digits)) + (2 - point if point <= 0 else (1 if point < len(digits) else 0))
    if length > 4096:
        return None, False
    if point <= 0:
        return '0.' + '0' * (-point) + digits, True
    if point >= len(digits):
        return digits + '0' * (point - len(digits)), True
    return digits[:point] + '.' + digits[point:], True


def read(tx, actor, project_id, work_order_id, resolve_subject):
    require_project(tx, actor, project_id)
    if not tx.execute('SELECT 1 FROM work_orders WHERE id=? AND project_id=?', (str(work_order_id), str(project_id))).fetchone():
        raise DomainError('NOT_FOUND', 404, 'Work order not found')
    binding = tx.execute('SELECT * FROM mes_order_bindings WHERE project_id=? AND work_order_id=? AND active=1', (str(project_id), str(work_order_id))).fetchone()
    result = {'work_order_id': str(work_order_id), 'can_manage': can_manage(tx, actor, project_id) and bool(resolve_subject(actor.user_id)), 'binding': None, 'snapshot': None}
    if binding:
        result['binding'] = {key: binding[key] for key in ('id', 'shop_order', 'environment', 'site_code', 'verified_at')}
        snapshot = tx.execute('SELECT * FROM mes_material_snapshots WHERE binding_id=? ORDER BY rowid DESC LIMIT 1', (binding['id'],)).fetchone()
        if snapshot:
            result['snapshot'] = {key: snapshot[key] for key in ('id', 'collected_at', 'total')}
            result['snapshot']['components'] = [dict(r) for r in tx.execute('SELECT component_key,material_id,required_quantity,withdrawn_quantity,unit,storage_location FROM mes_material_components WHERE snapshot_id=? ORDER BY position', (snapshot['id'],))]
            from .quantity_provenance import QuantitySource, quantity
            for component in result['snapshot']['components']:
                component['quantities'] = {}
                for name in ('required_quantity', 'withdrawn_quantity'):
                    reference = json.dumps([str(project_id), str(work_order_id), binding['id'],
                        binding['namespace'], binding['environment'], binding['shop_order'],
                        snapshot['id'], component['component_key'], name], separators=(',', ':'))
                    projected, representable = plain_quantity(component[name])
                    meaning = name if representable else f'{name}; quantity verification required: plain expansion exceeds safe limit or is invalid'
                    source = QuantitySource(reference=reference, project_id=str(project_id),
                        object_kind='mes_component', object_id=component['component_key'],
                        system='mes', source_type='order_component', external_id=binding['shop_order'],
                        version=snapshot['id'], namespace=binding['namespace'], origin='native',
                        environment=binding['environment'] if binding['environment'] in ('production', 'test', 'development', 'mock') else 'unknown',
                        occurred_at=None, collected_at=snapshot['collected_at'], coverage='complete' if representable else 'unknown',
                        value=projected, unit=component['unit'], meaning=meaning)
                    component['quantities'][name] = quantity(projected, component['unit'], name,
                        [source], fact_role='observation').model_dump(mode='json')
    return result


def placeholder(tx, context, command):
    raise RuntimeError('native order commands require preflight')


for model in (BindMesOrder, RefreshMesOrder):
    COMMAND_REGISTRY.register(model, roles={'project_owner', 'engineering'}, qualifications=set(), handler=placeholder)
