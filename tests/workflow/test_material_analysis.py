import sqlite3

from .conftest import BASE
from .test_exchanges import reserve, stock, act


def test_expired_or_frozen_lot_is_not_usable_in_single_or_batch_balance(workflow):
    p, req, supply, result = reserve(workflow)
    stock(workflow, p, supply)
    act(workflow, p, result)
    assert workflow.balance(p['id'], req['id'])['shortage'] == '20'
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("UPDATE material_lots SET expiry='2000-01-01' WHERE id=?", (supply['lot_id'],))
    assert workflow.balance(p['id'], req['id'])['shortage'] == '100'
    page = workflow.client().get(f"{BASE}/projects/{p['id']}/objects/requirement").json()
    row = next(x for x in page['items'] if x['id'] == req['id'])
    assert row['material_balance']['shortage'] == '100'
