"""Reusable isolated synthetic history, never production acceptance evidence."""
import json
import sqlite3
from uuid import uuid4

from .conftest import USERS


def clone_row(db, table, ident, **updates):
    row = dict(db.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone())
    row.update(updates)
    columns = list(row)
    db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(row.values()))
    return row


def large_material_history(workflow, count=52):
    """Return project/other_project, requirements/handoffs, tail and related IDs.

    Seed real local workflow commands, then clone explicit synthetic SQLite history.
    Every requirement has a distinct lot, receipt, IQC, and handoff. The last
    receipt is explicitly mock. No source adapter or production connection is used.
    """
    project, req, related = workflow.material_requirement(mode='oem')
    other, other_req, other_related = workflow.material_requirement(mode='oem')
    pid = project['id']
    workflow.grant(pid, 'warehouse', ['warehouse'])
    workflow.grant(pid, 'production', ['production'])
    first_hand = workflow.command(pid, 'material_handoff.record', actor_name='warehouse',
        material_lot_id=related['lot_id'], work_order_id=related['work_order_id'],
        quantity='1', unit='kg', from_location='Warehouse', to_location='Line',
        receiver_id=str(USERS['production']))['object_id']
    requirements, handoffs = [req['id']], [first_hand]
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        receipt = db.execute('SELECT id FROM supply_receipts WHERE project_id=?', (pid,)).fetchone()[0]
        iqc = db.execute('SELECT id FROM iqc_results WHERE receipt_id=?', (receipt,)).fetchone()[0]
        for index in range(1, count):
            rid, lid, cid, recid, iid, hid = (str(uuid4()) for _ in range(6))
            material = f'synthetic-{index:03d}'
            unit = 'g' if index == 1 else 'kg'
            owner = 'Other owner' if index == 2 else 'Customer 1'
            created = f'2099-01-01T00:00:{index:02d}+00:00'
            clone_row(db, 'requirements', req['id'], id=rid, lineage_id=str(uuid4()), material_id=material, unit=unit, owner_id=owner, created_at=created)
            lot = clone_row(db, 'material_lots', related['lot_id'], id=lid, material_id=material, unit=unit, owner_id=owner, lot_id=lid, source_external_id=lid)
            clone_row(db, 'supply_commitments', related['id'], id=cid, requirement_id=rid, unit=unit, owner_id=owner)
            source = workflow.source(recid, object_type='receipt', version=2 if index == 3 else 1,
                                     mode='mock' if index == count-1 else 'manual')
            clone_row(db, 'supply_receipts', receipt, id=recid, commitment_id=cid, material_lot_id=lid, unit=unit,
                      source_external_id=recid, source_version=source['version'], source_json=json.dumps(source))
            clone_row(db, 'iqc_results', iqc, id=iid, receipt_id=recid)
            hand = dict(db.execute('SELECT * FROM material_handoffs WHERE id=?', (first_hand,)).fetchone())
            payload = json.loads(hand['payload_json'])
            payload.update(id=hid, material_lot_id=lid, unit=unit, handoff_number=f'SYNTHETIC-{index}')
            payload['source'].update(external_id=hid)
            hand.pop('seq')
            hand.update(id=hid, material_lot_id=lid, payload_json=json.dumps(payload))
            db.execute(f"INSERT INTO material_handoffs ({','.join(hand)}) VALUES ({','.join('?' for _ in hand)})", list(hand.values()))
            requirements.append(rid)
            handoffs.append(hid)
    return dict(project=project, other_project=other, other_requirement=other_req,
                other_related=other_related, related=related, requirements=requirements,
                handoffs=handoffs, tail=requirements[-1])
