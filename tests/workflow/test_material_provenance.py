"""Quantity graphs over isolated persisted workflow facts; no source IO."""
import json
from .conftest import BASE, USERS
from .material_provenance_fixtures import large_material_history, clone_row


def page(workflow, pid, **params):
    response = workflow.client().get(f'{BASE}/projects/{pid}/material-control', params=params)
    assert response.status_code == 200, response.text
    return response.json()


def quantities(response):
    values = [q for kind in ('requirements', 'receipts', 'handoffs', 'work_orders')
              for row in response[kind] for q in row['quantities'].values()]
    values += [i['quantity_fact'] for r in response['requirements'] for i in r['issues'] if i.get('quantity_fact')]
    return values


def assert_modes(response):
    expected = sorted({'api' if origin == 'native' else origin for q in quantities(response) for origin in q['origins']})
    assert response['source_modes'] == expected
    assert response['source_modes_scope'] == 'returned_quantities'


def test_page_modes_values_and_read_only_provenance(workflow):
    p, req, related = workflow.material_requirement(mode='oem')
    with workflow.db() as db:
        before = list(db.iterdump())
    result = page(workflow, p['id'])
    assert_modes(result)
    row = result['requirements'][0]
    assert set(row['quantities']) == {'required', 'received', 'in_transit', 'qualified', 'rejected', 'reserved', 'shortage', 'confirmed_satisfied'}
    assert all(q['value'] == row[k] for k, q in row['quantities'].items())
    receipt = result['receipts'][0]
    assert all(q['value'] == receipt[k] for k, q in receipt['quantities'].items())
    assert receipt['quantities']['qualified']['origins'] == ['manual']
    assert any(s['object_kind'] == 'iqc' and s['occurred_at'] is None and s['collected_at'] for s in receipt['quantities']['qualified']['source_refs'])
    assert all(s['project_id'] == p['id'] for q in quantities(result) for s in q['source_refs'])
    assert all(not ({'evidence', 'signature', 'request_json'} & set(s)) for q in quantities(result) for s in q['source_refs'])
    with workflow.db() as db:
        assert list(db.iterdump()) == before
    workflow.reopen()
    assert page(workflow, p['id'])['requirements'][0]['quantities'] == row['quantities']
    assert page(workflow, p['id'], offset=1)['source_modes'] == []


def test_large_fixture_scope_tail_mock_and_overview(workflow):
    fixture = large_material_history(workflow)
    pid = fixture['project']['id']
    first = page(workflow, pid, limit=1)
    tail = page(workflow, pid, limit=1, offset=51)
    assert first['total'] == tail['total'] == 52
    assert tail['requirements'][0]['id'] == fixture['tail']
    assert_modes(first); assert_modes(tail)
    assert 'mock' not in first['source_modes']
    row = tail['requirements'][0]
    assert 'mock' in row['quantities']['received']['origins']
    assert 'mock' not in row['quantities']['required']['origins']
    assert len(fixture['handoffs']) == 52
    filtered = page(workflow, pid, search='synthetic-051')
    assert filtered['requirements'][0]['quantities'] == row['quantities']
    assert all(s['project_id'] == pid for q in quantities(tail) for s in q['source_refs'])
    overview = workflow.client().get(f'{BASE}/material-control/overview').json()
    assert all(r['source_modes_scope'] == 'project_source_records' for r in overview['items'])


def test_handoff_sender_receiver_are_distinct_and_unsigned_is_null(workflow):
    p, req, related = workflow.material_requirement(mode='oem')
    pid = p['id']
    workflow.grant(pid, 'warehouse', ['warehouse'])
    workflow.grant(pid, 'production', ['production'])
    hid = workflow.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=related['lot_id'],
        work_order_id=related['work_order_id'], quantity='20', unit='kg', from_location='Warehouse', to_location='Line',
        receiver_id=str(USERS['production']))['object_id']
    first = page(workflow, pid)
    assert first['handoffs'][0]['quantities']['received_quantity']['value'] is None
    workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=hid, received_quantity='18',
                     received_location='Line', note='Short', receipt_use='line_side', requirement_id=req['id'])
    result = page(workflow, pid)
    hand = result['handoffs'][0]
    sent, received = hand['quantities']['quantity'], hand['quantities']['received_quantity']
    assert sent['value'] == '20' and received['value'] == '18'
    assert set(sent['input_refs']).isdisjoint(received['input_refs'])
    assert received['source_refs'][0]['collected_at'] == hand['receipt']['recorded_at']
    issue = next(i for i in result['requirements'][0]['issues'] if i['code'] == 'unreceived')
    assert issue['quantity_fact']['value'] == '2'
    assert set(sent['input_refs'] + received['input_refs']) <= set(issue['quantity_fact']['input_refs'])
    assert_modes(result)


def test_authority_corrections_keep_delta_exchange_and_exact_iqc_identity(workflow):
    from .test_exchanges import reserve
    from .test_imports import review_receipt, review_iqc, review_import, review_pull, review_correct
    p, req, related, _ = reserve(workflow)
    pid = p['id']
    original = review_receipt(workflow, p, related)
    rec = review_import(workflow, p, original, 'supply', quantity='80')['object_id']
    first = review_iqc(workflow, p, 'iqc-one', '30')
    second = review_iqc(workflow, p, 'iqc-two', '20')
    review_import(workflow, p, first, 'quality', accepted='20')
    review_import(workflow, p, second, 'quality')
    receipt_pull = review_pull(workflow, p, 'receipt', 'review-delivery', 'supply')
    review_correct(workflow, p, receipt_pull, 'receipt', 'review-delivery', actor='supply')
    iqc_pull = review_pull(workflow, p, 'iqc', 'iqc-one', 'quality')
    review_correct(workflow, p, iqc_pull, 'iqc', 'iqc-one')
    result = page(workflow, pid)
    row = result['requirements'][0]
    assert (row['received'], row['qualified'], row['in_transit']) == ('100', '50', '0')
    with workflow.db() as db:
        corrections = [dict(r) for r in db.execute('SELECT * FROM source_corrections WHERE project_id=?', (pid,))]
        confirms = [dict(r) for r in db.execute("SELECT * FROM source_confirmations WHERE project_id=? AND object_type='iqc'", (pid,))]
    for correction in corrections:
        field = 'qualified' if correction['iqc_id'] else 'received'
        found = [s for s in row['quantities'][field]['source_refs'] if s['object_kind'] == 'source_correction' and s['object_id'] == str(correction['seq'])]
        assert len(found) == 1 and found[0]['origin'] == 'mock'
        assert correction['exchange_id'] in found[0]['meaning']
        assert found[0]['value'] == ('10' if correction['iqc_id'] else '20')
    for confirmation in confirms:
        found = [s for s in row['quantities']['qualified']['source_refs'] if s['object_kind'] == 'source_confirmation' and s['object_id'] == str(confirmation['seq'])]
        assert len(found) == 1 and confirmation['fact_id'] in found[0]['meaning']
    assert 'mock' in row['quantities']['in_transit']['origins']  # clamped zero preserves mock
    assert_modes(result)


def test_many_receipts_and_corrections_are_not_preview_capped(workflow):
    import sqlite3
    from uuid import uuid4
    from .test_exchanges import reserve
    p, req, related, reservation = reserve(workflow)
    rec = workflow.receive(p['id'], related['id'], quantity='1', lot_id=related['lot_id'])['object_id']
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        for i in range(205):
            ident = str(uuid4())
            source = workflow.source(ident, object_type='receipt', mode='mock' if i == 204 else 'manual')
            clone_row(db, 'supply_receipts', rec, id=ident, q_atoms=1, source_external_id=ident, source_json=json.dumps(source))
        for _ in range(505):
            db.execute('INSERT INTO source_corrections(project_id,receipt_id,received_delta,exchange_id,evidence) VALUES (?,?,?,?,?)',
                       (p['id'], rec, 0, reservation['exchange_id'], 'Isolated unresolved historical correction'))
    result = page(workflow, p['id'])
    assert len(result['receipts']) == 200
    q = result['requirements'][0]['quantities']['received']
    assert q['value'] == '1.205'
    assert len([s for s in q['source_refs'] if s['object_kind'] == 'receipt']) == 206
    assert len([s for s in q['source_refs'] if s['object_kind'] == 'source_correction']) == 505
    assert {'mock', 'unknown'} <= set(q['origins']) and q['coverage'] == 'unknown'
    assert_modes(result)


def test_reservation_acceptance_shared_quality_and_unknown_eligibility(workflow):
    import sqlite3
    from uuid import uuid4
    from .test_exchanges import reserve, stock, act
    p, req, related, reservation = reserve(workflow)
    stock(workflow, p, related); act(workflow, p, reservation)
    rec = workflow.receive(p['id'], related['id'], quantity='100', lot_id=related['lot_id'])['object_id']
    workflow.inspect(p['id'], rec, accepted='100', rejected='0')
    result = page(workflow, p['id'])
    values = result['requirements'][0]['quantities']
    assert values['reserved']['value'] == '80' and 'mock' in values['reserved']['origins']
    assert values['confirmed_satisfied']['value'] == '80'
    assert values['shortage']['coverage'] == 'unknown'
    assert any(s['object_kind'] == 'lot_eligibility' for s in values['shortage']['source_refs'])
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("UPDATE material_lots SET state='frozen' WHERE id=?", (related['lot_id'],))
    frozen = page(workflow, p['id'])['requirements'][0]
    assert frozen['shortage'] == frozen['quantities']['shortage']['value'] == '100'
    assert any('state=frozen' in s['meaning'] for s in frozen['quantities']['shortage']['source_refs'])


def test_same_lineage_different_dimensions_never_leak(workflow):
    import sqlite3
    from uuid import uuid4
    p, req, related = workflow.material_requirement()
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        rec = db.execute('SELECT id FROM supply_receipts WHERE project_id=?', (p['id'],)).fetchone()[0]
        original = dict(db.execute('SELECT * FROM requirements WHERE id=?', (req['id'],)).fetchone())
        for change in ({'material_id': 'different'}, {'owner_id': 'other'}, {'unit': 'g'}, {'scale': 2}):
            rid, cid, recid = (str(uuid4()) for _ in range(3))
            clone_row(db, 'requirements', req['id'], id=rid, **change)
            clone_row(db, 'supply_commitments', related['id'], id=cid, requirement_id=rid)
            source = workflow.source(recid, object_type='receipt', mode='mock')
            clone_row(db, 'supply_receipts', rec, id=recid, commitment_id=cid, source_external_id=recid, source_json=json.dumps(source))
    result = page(workflow, p['id'], requirement_id=req['id'])
    assert 'mock' not in result['source_modes']
    assert result['requirements'][0]['quantities']['received']['value'] == '80'


def test_integration_release_graph_only_uses_full_matching_hash(tmp_path):
    import sqlite3
    from .integrations.support import MockRig, NOW
    rig = MockRig(tmp_path, core=True)
    refs = rig.start_ready()
    rig.execute('mes', refs.start_payload)
    execution = rig.pass_unit(refs)
    rig.execute('mes', dict(operation='mes.complete', work_order_id=str(refs.work_order), revision_id=str(refs.revision),
        units=refs.units, execution_sources=[execution.source_key.model_dump()],
        consumption=[a.model_dump(mode='json') for a in execution.payload.material_uses], occurred_at=NOW.isoformat()))
    needed = rig.registry.adapter('mes').facts(rig.project_id, 'return_requirement', 0, 200).records[-1]
    payload = needed.payload.model_dump(mode='json', exclude={'fact_type'}) | {'cause': needed.source_key.model_dump()}
    returned = rig.result_fact(rig.execute('wms', dict(operation='wms.return', direction='to_warehouse', **payload)))
    reservation = rig.registry.adapter('wms').facts(rig.project_id, 'reservation', 0, 200).records[0]
    release = rig.result_fact(rig.execute('wms', dict(operation='wms.release_reservation',
        work_order_id=str(refs.work_order), reservation=reservation.source_key.model_dump(),
        allocations=[a.model_dump(mode='json') for a in returned.payload.allocations],
        cause=returned.source_key.model_dump(), evidence='Isolated explicit release')))
    from manufacturing_platform.workflow.material_control import project_view
    result = project_view(rig.workflow, rig.actor, rig.project_id, 50, 0).model_dump(mode='json')
    row = next(r for r in result['requirements'] if r['id'] == str(refs.requirement))
    q = row['quantities']['reserved']
    assert q['value'] == '1'
    matching = [s for s in q['source_refs'] if s['external_id'] == release.source.external_id and s['value'] == '-11']
    assert len(matching) == 1 and matching[0]['origin'] == 'mock'
    with rig.workflow.store.transaction() as tx:
        before = dict(tx.execute('SELECT * FROM integration_reservation_releases WHERE project_id=?', (str(rig.project_id),)).fetchone())
        projection = dict(tx.execute("SELECT * FROM integration_projections WHERE project_id=? AND object_type='reservation_release'", (str(rig.project_id),)).fetchone())
        projection.update(external_id='synthetic-mismatched', payload_hash='b'*64)
        tx.execute(f"INSERT INTO integration_projections ({','.join(projection)}) VALUES ({','.join('?' for _ in projection)})", list(projection.values()))
        before.update(external_id='synthetic-mismatched', payload_hash='a'*64, q_atoms=1)
        tx.execute(f"INSERT INTO integration_reservation_releases ({','.join(before)}) VALUES ({','.join('?' for _ in before)})", list(before.values()))
    after = project_view(rig.workflow, rig.actor, rig.project_id, 50, 0).model_dump(mode='json')
    assert next(r for r in after['requirements'] if r['id'] == str(refs.requirement))['quantities']['reserved'] == q
    assert_modes(after)


def test_partial_exclusive_supplement_issue_keeps_actual_receipt_inputs(workflow):
    import sqlite3
    from .test_material_tasks import setup
    pid, rid, related = setup(workflow)
    def hand(sent, signed):
        hid = workflow.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=related['lot_id'],
            work_order_id=related['work_order_id'], quantity=sent, unit='kg', from_location='Warehouse', to_location='Line',
            receiver_id=str(USERS['production']))['object_id']
        workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=hid,
                         received_quantity=signed, received_location='Line', note='Short')
        return hid
    original, supplement, unrelated = hand('20', '18'), hand('1', '1'), hand('10', '10')
    task = workflow.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid, task_kind='trace',
                            handoff_id=original, assignee_id=str(USERS['warehouse']), note='Trace')['object_id']
    # An explicit synthetic historical partial link, retained for graph regression.
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute('INSERT INTO material_task_evidence VALUES (?,?,?)', (pid, task, supplement))
    result = page(workflow, pid)
    issue = next(i for i in result['requirements'][0]['issues'] if i['object_id'] == original and i['code'] == 'unreceived')
    assert issue['quantity'] == issue['quantity_fact']['value'] == '1'
    ids = {s['object_id'] for s in issue['quantity_fact']['source_refs']}
    assert {original, supplement} <= ids and unrelated not in ids
    assert any(s['object_kind'] == 'material_task_evidence' for s in issue['quantity_fact']['source_refs'])


def test_qualified_graph_retains_receipt_association(workflow):
    p, _, _ = workflow.material_requirement()
    result = page(workflow, p['id'])
    rec = result['receipts'][0]
    q = rec['quantities']['qualified']
    assert any(s['object_kind'] == 'receipt' and s['object_id'] == rec['id'] for s in q['source_refs'])


def test_confirmation_for_wrong_iqc_fact_does_not_leak(workflow):
    import sqlite3
    from .test_exchanges import reserve
    from .test_imports import review_receipt, review_import, review_iqc
    p, req, related, _ = reserve(workflow)
    rec = review_import(workflow, p, review_receipt(workflow, p, related), 'supply')['object_id']
    review_import(workflow, p, review_iqc(workflow, p, 'iqc-a', '10'), 'quality')
    review_import(workflow, p, review_iqc(workflow, p, 'iqc-b', '20'), 'quality')
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("UPDATE source_confirmations SET fact_id='unrelated', mode='mock', source_json=json_set(source_json,'$.mode','mock') WHERE external_id='iqc-b'")
    result = page(workflow, p['id'])
    q = result['requirements'][0]['quantities']['qualified']
    assert q['value'] == '30' and 'mock' not in q['origins']
    assert not any(s['external_id'] == 'iqc-b' for s in q['source_refs'])


def test_reservation_only_never_turns_unverified_quality_into_zero(workflow):
    from .test_exchanges import reserve, stock, act
    p, req, related, reservation = reserve(workflow)
    stock(workflow, p, related); act(workflow, p, reservation)
    row = page(workflow, p['id'])['requirements'][0]
    assert row['confirmed_satisfied'] is row['quantities']['confirmed_satisfied']['value'] is None
    assert row['quantities']['confirmed_satisfied']['fact_role'] == 'unknown'
    assert 'mock' in row['quantities']['confirmed_satisfied']['origins']


def test_correction_retained_payload_must_match_its_confirmation(workflow):
    import sqlite3
    from .test_exchanges import reserve
    from .test_imports import review_receipt, review_import, review_pull, review_correct
    p, _, related, _ = reserve(workflow)
    review_import(workflow, p, review_receipt(workflow, p, related), 'supply', quantity='80')
    pull = review_pull(workflow, p, 'receipt', 'review-delivery', 'supply')
    review_correct(workflow, p, pull, 'receipt', 'review-delivery', actor='supply')
    # Synthetic corrupt retained record: same labels, different business target.
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("UPDATE exchange_events SET payload_json=json_set(payload_json,'$.records[0].commitment_id','00000000-0000-4000-8000-000000000099') WHERE exchange_id=? AND json_type(payload_json,'$.records')='array'", (pull['exchange_id'],))
    q = page(workflow, p['id'])['requirements'][0]['quantities']['received']
    corrections = [s for s in q['source_refs'] if s['object_kind'] == 'source_correction']
    assert q['value'] == '100' and len(corrections) == 1
    assert corrections[0]['origin'] == 'unknown' and corrections[0]['value'] == '20'
    assert pull['exchange_id'] in corrections[0]['meaning']


def test_overview_scans_past_501_and_api_identity_stays_unknown(workflow):
    import sqlite3
    from uuid import uuid4
    p, req, related = workflow.material_requirement()
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        rec = db.execute('SELECT id FROM supply_receipts WHERE project_id=?', (p['id'],)).fetchone()[0]
        for index in range(502):
            ident = str(uuid4())
            source = workflow.source(ident, object_type='receipt', mode='mock' if index == 501 else 'manual')
            clone_row(db, 'supply_receipts', rec, id=ident, q_atoms=1, source_external_id=ident, source_json=json.dumps(source))
        # Labels cannot grant native/production identity to a historical API fact.
        db.execute("UPDATE work_orders SET source_json=json_set(source_json,'$.mode','api','$.system','mes') WHERE project_id=?", (p['id'],))
    overview = workflow.client().get(f'{BASE}/material-control/overview').json()['items'][0]
    assert overview['source_modes_scope'] == 'project_source_records'
    assert {'mock', 'unknown'} <= set(overview['source_modes']) and 'api' not in overview['source_modes']
    result = page(workflow, p['id'], limit=1)
    q = result['work_orders'][0]['quantities']['quantity']
    assert q['origins'] == ['unknown'] and q['environments'] == ['unknown']
    assert q['observed_at'] == '2026-10-28T08:00:00Z'


def test_shared_lot_competing_claim_is_in_filtered_requirement_graph(workflow):
    import sqlite3
    from uuid import uuid4
    from .test_exchanges import reserve, stock, act
    p, req, related, reservation = reserve(workflow)
    stock(workflow, p, related); act(workflow, p, reservation)
    rec = workflow.receive(p['id'], related['id'], quantity='100', lot_id=related['lot_id'])['object_id']
    workflow.inspect(p['id'], rec, accepted='100', rejected='0')
    competing_req, competing_wo, competing_claim = (str(uuid4()) for _ in range(3))
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        claim = db.execute('SELECT id FROM reservations WHERE project_id=?', (p['id'],)).fetchone()[0]
        clone_row(db, 'work_orders', related['work_order_id'], id=competing_wo, source_external_id=competing_wo)
        clone_row(db, 'requirements', req['id'], id=competing_req, lineage_id=competing_req, work_order_id=competing_wo)
        clone_row(db, 'reservations', claim, id=competing_claim, requirement_id=competing_req, work_order_id=competing_wo,
                  exchange_id=None, authority_receipt_id=str(uuid4()))
    row = page(workflow, p['id'], requirement_id=req['id'])['requirements'][0]
    q = row['quantities']['confirmed_satisfied']
    assert q['value'] is None
    assert any(s['object_kind'] == 'reservation' and s['object_id'] == competing_claim and s['origin'] == 'unknown' for s in q['source_refs'])
    assert not any(s['object_id'] == competing_claim for s in row['quantities']['reserved']['source_refs'])


def test_source_reader_batches_each_project_table_once(workflow):
    from manufacturing_platform.workflow.material_provenance import requirement_quantities
    from manufacturing_platform.workflow.material_analysis import analyze
    fixture = large_material_history(workflow)
    pid = fixture['project']['id']
    with workflow.db() as db:
        rows = db.execute('SELECT r.*,p.cutoff,p.source_version FROM requirements r JOIN plans p ON p.id=r.plan_id WHERE r.project_id=?', (pid,)).fetchall()
        balances, _, unknown, _ = analyze(db, pid, rows)
        statements = []
        db.set_trace_callback(statements.append)
        values = requirement_quantities(db, pid, rows, balances, unknown)
        assert len(values) == 52
        reads = [s for s in statements if s.startswith('SELECT * FROM ')]
        assert len(reads) == len(set(reads))
        assert all(f"project_id='{pid}'" in s for s in reads)
        assert all(fixture['other_project']['id'] not in s for s in statements)
        assert len(statements) < 30


def test_imported_and_later_confirmed_iqc_preserve_ambiguous_original_identity(workflow):
    from .test_exchanges import reserve
    from .test_imports import review_receipt, review_import, review_iqc, review_pull
    p, _, related, _ = reserve(workflow)
    pid = p['id']
    rec = review_import(workflow, p, review_receipt(workflow, p, related), 'supply')['object_id']
    workflow.inspect(pid, rec, accepted='10', rejected='0')
    with workflow.db() as db:
        manual = db.execute('SELECT id FROM iqc_results WHERE receipt_id=?', (rec,)).fetchone()[0]
    review_iqc(workflow, p, 'confirmed-local', '10', manual_iqc_id=manual)
    review_pull(workflow, p, 'iqc', 'confirmed-local', 'quality')
    review_import(workflow, p, review_iqc(workflow, p, 'import-only', '20'), 'quality')
    workflow.inspect(pid, rec, accepted='5', rejected='0')
    q = page(workflow, pid)['receipts'][0]['quantities']['qualified']
    assert q['value'] == '35'
    events = {s['value']: s for s in q['source_refs'] if s['object_kind'] == 'iqc' and s['meaning'] == 'accepted'}
    assert events['10']['origin'] == events['20']['origin'] == 'unknown'
    assert events['10']['object_id'] == manual and events['10']['collected_at']
    assert events['5']['origin'] == 'manual'
    confirmations = {s['external_id']: s['origin'] for s in q['source_refs'] if s['object_kind'] == 'source_confirmation'}
    assert confirmations['confirmed-local'] == 'mock' and confirmations['import-only'] == 'file'
    overview = workflow.client().get(f'{BASE}/material-control/overview').json()['items'][0]
    assert 'unknown' in overview['source_modes']


def test_shared_projectors_reject_foreign_and_missing_objects(workflow):
    import pytest
    from manufacturing_platform.workflow.material_provenance import requirement_quantities, handoff_quantities
    fixture = large_material_history(workflow, count=1)
    pid = fixture['project']['id']
    with workflow.db() as db:
        foreign = dict(db.execute('SELECT * FROM requirements WHERE id=?', (fixture['other_requirement']['id'],)).fetchone())
        local = dict(db.execute('SELECT * FROM requirements WHERE id=?', (fixture['requirements'][0],)).fetchone())
        hand = json.loads(db.execute('SELECT payload_json FROM material_handoffs WHERE id=?', (fixture['handoffs'][0],)).fetchone()[0])
        hand['receipt'] = None
        foreign_hand = dict(hand, id='missing-handoff')
        for row in (foreign, dict(local, id='missing-requirement')):
            with pytest.raises(ValueError):
                requirement_quantities(db, pid, [row], {}, set())
        with pytest.raises(ValueError):
            handoff_quantities(db, fixture['other_project']['id'], hand)
        with pytest.raises(ValueError):
            handoff_quantities(db, pid, foreign_hand)


def test_shared_requirement_rejects_changed_quantity_and_scope_before_balance(workflow):
    import pytest
    from manufacturing_platform.workflow.material_provenance import requirement_quantities
    p, req, _ = workflow.material_requirement(mode='oem')
    with workflow.db() as db:
        row = dict(db.execute('SELECT * FROM requirements WHERE id=?', (req['id'],)).fetchone())
        for field, value in [('q_atoms', row['q_atoms'] + 1), ('lineage_id', 'altered'),
                             ('work_order_id', 'altered'), ('material_id', 'altered'),
                             ('owner_id', 'altered'), ('unit', 'altered'), ('scale', row['scale'] + 1),
                             ('plan_id', 'altered'), ('execution_scope', 'altered')]:
            with pytest.raises(ValueError):
                requirement_quantities(db, p['id'], [dict(row, **{field: value})], {}, set())


def test_shared_handoff_rejects_changed_persisted_facts(workflow):
    import copy
    import pytest
    from manufacturing_platform.workflow.material_provenance import handoff_quantities
    p, req, related = workflow.material_requirement(mode='oem')
    pid = p['id']
    workflow.grant(pid, 'warehouse', ['warehouse'])
    workflow.grant(pid, 'production', ['production'])
    hid = workflow.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=related['lot_id'],
        work_order_id=related['work_order_id'], quantity='20', unit='kg', from_location='Warehouse', to_location='Line',
        receiver_id=str(USERS['production']))['object_id']
    workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=hid, received_quantity='18',
                     received_location='Line', note='Short', receipt_use='line_side', requirement_id=req['id'])
    with workflow.db() as db:
        saved = db.execute('SELECT payload_json,receipt_json FROM material_handoffs WHERE id=?', (hid,)).fetchone()
        hand = json.loads(saved['payload_json'])
        hand['receipt'] = json.loads(saved['receipt_json'])
        for path, value in [(('quantity',), '999'), (('unit',), 'g'), (('source', 'external_id'), 'fake'),
                            (('material_lot_id',), 'fake'), (('work_order_id',), 'fake'),
                            (('receipt',), None), (('receipt', 'received_quantity'), '999'),
                            (('receipt', 'received_location'), 'fake'), (('receipt', 'receipt_use'), 'unspecified'),
                            (('receipt', 'requirement_id'), 'fake'), (('receipt', 'actor_id'), 'fake')]:
            changed = copy.deepcopy(hand)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with pytest.raises(ValueError):
                handoff_quantities(db, pid, changed)
        facts = handoff_quantities(db, pid, hand)
        assert facts['quantity'].value == '20'
        assert facts['received_quantity'].value == '18'


def test_shared_work_order_rejects_foreign_missing_and_altered_quantities(workflow):
    import pytest
    from manufacturing_platform.workflow.material_provenance import work_order_quantities
    from manufacturing_platform.workflow.material_source_reader import MaterialSources
    p, _, _ = workflow.material_requirement(mode='oem')
    other, _, _ = workflow.material_requirement(mode='oem')
    item = page(workflow, p['id'])['work_orders'][0]
    with workflow.db() as db:
        reader = MaterialSources(db, p['id'])
        with pytest.raises(ValueError):
            work_order_quantities(MaterialSources(db, other['id']), item)
        for field, value in [('id', 'missing'), ('quantity', '999'), ('trial_quantity', '999'), ('unit', 'fake')]:
            with pytest.raises(ValueError):
                work_order_quantities(reader, dict(item, **{field: value}))
        result = work_order_quantities(reader, item)
        assert result['quantity'].value == item['quantity']
        assert result['trial_quantity'].value == item['trial_quantity']
