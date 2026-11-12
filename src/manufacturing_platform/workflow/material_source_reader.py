"""Transaction-local, project-scoped persisted evidence. Never invokes a source.

Enumeration covers platform records, not completeness of an external inventory.
Indexes are built once per page; quantities reuse the same immutable read basis.
"""
import hashlib
import json
from collections import defaultdict

from pydantic import ValidationError

from .quantity_provenance import QuantitySource, source_from_ref
from .supply import amount
from .orders import source_key


def scope(row, work_order=None):
    return (row['lineage_id'], work_order or row['work_order_id'], row['material_id'],
            row['owner_id'], row['unit'], row['scale'])


def key(source):
    try:
        identity = source_key(source)
    except (KeyError, AttributeError, TypeError, ValueError):
        identity = tuple(source.get(k) for k in ('system', 'object_type', 'external_id'))
    return (*identity, source.get('version'))


class MaterialSources:
    """One bounded project universe; no arbitrary preview limits or global cache."""
    def __init__(self, tx, project_id):
        self.tx, self.pid = tx, str(project_id)
        self.tables = {}
        self.indexes = {}
        self.receipt_cache = {}
        self.reservation_cache = {}
        self.required_cache = {}
        self.eligibility_cache = {}

    def rows(self, table):
        if table not in self.tables:
            order = 'seq' if table == 'effective_material_movements' else 'rowid'
            self.tables[table] = [dict(r) for r in self.tx.execute(
                f'SELECT * FROM {table} WHERE project_id=? ORDER BY {order}', (self.pid,))]
        return self.tables[table]

    def by(self, table, column, value):
        cache_key = (table, column)
        if cache_key not in self.indexes:
            grouped = defaultdict(list)
            for row in self.rows(table):
                grouped[row[column]].append(row)
            self.indexes[cache_key] = grouped
        return self.indexes[cache_key].get(value, [])

    def one(self, table, ident):
        rows = self.by(table, 'id', str(ident))
        return rows[0] if rows else None

    def leaf(self, source, kind, ident, meaning, value=None, unit=None, **kwargs):
        source = source or {}
        # Local identity is part of the reference: equal source keys never erase
        # a correction, a distinct declaration, or an input with another meaning.
        ref = json.dumps([self.pid, kind, str(ident), meaning,
                          *key(source), source.get('mode'), kwargs.get('namespace'),
                          kwargs.get('environment', 'unknown')], separators=(',', ':'))
        return source_from_ref(source, reference=ref, project_id=self.pid,
            object_kind=kind, object_id=str(ident), value=value, unit=unit, meaning=meaning, **kwargs)

    def local(self, kind, ident, meaning, value=None, unit=None, *, manual=False,
              collected_at=None, occurred_at=None, actor=None, complete=False):
        ref = json.dumps([self.pid, kind, str(ident), meaning, actor], separators=(',', ':'))
        return QuantitySource(reference=ref, project_id=self.pid, object_kind=kind,
            object_id=str(ident), system=None, source_type=None, external_id=None,
            version=None, namespace=None, origin='manual' if manual else 'unknown',
            environment='unknown', occurred_at=occurred_at, collected_at=collected_at,
            coverage='complete' if complete else 'unknown', value=value, unit=unit, meaning=meaning)

    def row_leaf(self, row, kind, meaning, value=None, unit=None):
        return self.leaf(json.loads(row['source_json']), kind, row['id'], meaning, value, unit)

    def confirmations(self, object_type, object_id, fact_id):
        result = []
        for row in self.by('source_confirmations', 'fact_id', str(fact_id)):
            if row['object_type'] != object_type or row['object_id'] != str(object_id):
                continue
            source = json.loads(row['source_json'])
            if key(source) != tuple(row[k] for k in ('system', 'object_type', 'external_id', 'version')) or source.get('mode') != row['mode']:
                continue
            result.append(row)
        return result

    def confirmation_leaves(self, object_type, object_id, fact_id):
        return [self.leaf(json.loads(r['source_json']), 'source_confirmation', r['seq'],
                          f'{object_type} confirmation for {fact_id}')
                for r in self.confirmations(object_type, object_id, fact_id)]

    def inspection(self, row, meaning, value=None, unit=None):
        # Both imports and direct human inspections call inspect_supply. Once an
        # exact confirmation exists, this schema cannot prove the original method.
        # Preserve the original actor/time and confirmation as distinct identities.
        manual = not self.confirmations('iqc', row['receipt_id'], row['id'])
        return self.local('iqc', row['id'], meaning, value, unit, manual=manual,
            actor=row['actor_id'], collected_at=row['created_at'], complete=manual)

    def correction(self, row, field, scale, unit):
        source = None
        exchange = self.one('exchanges', row['exchange_id'])
        kind = 'iqc' if row['iqc_id'] else 'receipt'
        fact_id = row['iqc_id'] or row['receipt_id']
        if exchange and exchange['action'] == 'source.pull':
            records = [json.loads(r['payload_json'])['records'] for r in
                       self.by('exchange_events', 'exchange_id', exchange['id'])
                       if isinstance(json.loads(r['payload_json']).get('records'), list)]
            if records and len(records[-1]) == 1:
                record = records[-1][0]
                candidate = record.get('source', {})
                request = json.loads(exchange['request_json'])
                matches = self.confirmations(kind, row['receipt_id'], fact_id)
                if (str(record.get('project_id')) == self.pid and record.get('object_type') == kind
                    and candidate.get('mode') == exchange['mode']
                    and key(candidate)[:3] == key({'system': exchange['system'],
                        'object_type': request.get('object_type'),
                        'external_id': request.get('external_id')})[:3]
                    and request.get('object_type') == kind
                    and any(key(json.loads(c['source_json'])) == key(candidate)
                            and c['mode'] == candidate.get('mode')
                            and c['payload_hash'] == hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
                            for c in matches)):
                    source = candidate
        # Exchange and delta survive even when the historical source is unresolved.
        return self.leaf(source, 'source_correction', row['seq'],
            f'{field}; receipt={row["receipt_id"]}; iqc={row["iqc_id"]}; exchange={row["exchange_id"]}',
            amount(row[field], scale), unit)

    def integrations(self):
        if 'valid_integrations' not in self.indexes:
            from .integrations.contracts import IntegrationFact, ProjectionResult
            from .integrations.store import canonical_hash
            result = {}
            targets = defaultdict(list)
            for row in self.rows('integration_projections'):
                try:
                    fact = IntegrationFact.model_validate_json(row['fact_json'])
                    projection = ProjectionResult.model_validate_json(row['result_json'])
                except (ValidationError, ValueError):
                    continue
                identity = tuple(row[k] for k in ('system', 'object_type', 'external_id', 'version'))
                if (str(fact.project_id) != self.pid or str(projection.project_id) != self.pid
                    or key(fact.source.model_dump()) != identity or projection.source_key != fact.source_key
                    or canonical_hash(fact) != row['payload_hash'] or projection.payload_hash != row['payload_hash']):
                    continue
                result[identity] = (row, fact)
                for target in [*projection.targets, *projection.auxiliary]:
                    targets[(getattr(target.kind, 'value', target.kind), str(target.id))].append((row, fact))
            self.indexes['valid_integrations'] = result
            self.indexes['integration_targets'] = targets
        return self.indexes['valid_integrations']

    def integration_leaf(self, row, fact, meaning, value=None, unit=None, suffix=''):
        return self.leaf(fact.source.model_dump(mode='json'), 'integration_projection',
                         json.dumps([*key(fact.source.model_dump()), row['payload_hash'], suffix]), meaning, value, unit)

    def linked_integrations(self, kind, ident):
        self.integrations()
        return [self.integration_leaf(row, fact, f'projected {kind} association')
                for row, fact in self.indexes['integration_targets'].get((kind, str(ident)), [])]

    def releases(self, reservation, scale):
        if 'matched_releases' not in self.indexes:
            grouped = defaultdict(list)
            # This is deliberately identical to the effective_reservations join.
            for row in self.tx.execute('''SELECT d.* FROM integration_reservation_releases d
                JOIN integration_projections p ON p.project_id=d.project_id AND p.system=d.system
                AND p.object_type=d.object_type AND p.external_id=d.external_id
                AND p.version=d.version AND p.payload_hash=d.payload_hash
                WHERE d.project_id=? ORDER BY d.rowid''', (self.pid,)):
                grouped[row['reservation_id']].append(dict(row))
            self.indexes['matched_releases'] = grouped
        result = []
        for row in self.indexes['matched_releases'].get(reservation['id'], []):
            identity = tuple(row[k] for k in ('system', 'object_type', 'external_id', 'version'))
            value = amount(-row['q_atoms'], scale)
            meaning = (f'reservation release; reservation={reservation["id"]}; '
                       f'qualification={row["qualification_key"]}; receipt={row["receipt_system"]}/'
                       f'{row["receipt_external_id"]}/{row["receipt_version"]}')
            valid = self.integrations().get(identity)
            if valid:
                result.append(self.integration_leaf(*valid, meaning, value, reservation['unit'], suffix=row['qualification_key']))
                # Keep all persisted source dependencies, including release cause and qualification.
                for dependency in valid[1].caused_by:
                    dep = self.integrations().get(key(dependency.model_dump()))
                    if dep:
                        result.append(self.integration_leaf(*dep, 'reservation release basis'))
                    else:
                        result.append(self.leaf(None, 'integration_dependency', json.dumps(key(dependency.model_dump())), 'unresolved release basis'))
            else:
                result.append(self.leaf(None, 'reservation_release', json.dumps([*identity, row['qualification_key'], row['payload_hash']]), meaning, value, reservation['unit']))
        return result

    def reservation(self, reservation):
        ident = reservation['id']
        if ident in self.reservation_cache:
            return self.reservation_cache[ident]
        from .exchange_models import ExternalReceipt, ExternalRequest
        from .exchanges import receipt_scope
        req = self.one('requirements', reservation['requirement_id'])
        scale = req['scale']
        exchange = self.one('exchanges', reservation['exchange_id'])
        source = None
        if exchange and exchange['receipt_json']:
            try:
                receipt = ExternalReceipt.model_validate_json(exchange['receipt_json'])
                request = ExternalRequest.model_validate_json(exchange['request_json'])
                payload = request.typed_payload
                digest = hashlib.sha256(json.dumps(request.model_dump(mode='json'), sort_keys=True,
                    separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
                if (request.action == 'reservation.request' and str(request.project_id) == self.pid
                    and str(request.id) == exchange['id'] and request.system == exchange['system']
                    and digest == exchange['request_hash'] and request.business_key == exchange['business_key']
                    and str(receipt.receipt_id) == reservation['authority_receipt_id']
                    and receipt.sequence == reservation['accepted_sequence']
                    and receipt.source_version == reservation['source_version']
                    and receipt.phase in ('accepted', 'posted')
                    and str(payload.reservation_id) == ident
                    and receipt_scope(self.tx, exchange, receipt)):
                    source = dict(system=exchange['system'], object_type='reservation',
                        external_id=str(receipt.receipt_id), version=receipt.source_version,
                        mode=exchange['mode'], occurred_at=receipt.occurred_at.isoformat())
            except (ValidationError, ValueError, AttributeError):
                pass
        result = [self.leaf(source, 'reservation', ident,
            f'authority confirmed reservation; exchange={reservation["exchange_id"]}; receipt={reservation["authority_receipt_id"]}',
            amount(reservation['confirmed_atoms'], scale), reservation['unit'])]
        result += self.linked_integrations('reservation', ident)
        result += self.releases(reservation, scale)
        self.reservation_cache[ident] = result
        return result
