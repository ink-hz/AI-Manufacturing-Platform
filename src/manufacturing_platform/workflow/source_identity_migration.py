"""Schema16 canonical indexes; immutable source snapshots remain untouched."""

import json
from .orders import source_key


def migrate_source_identities(tx):
    updates = []
    scopes = {"orders": {}, "work_orders": {}}
    for table in ("demands", "order_lines", "work_orders"):
        seen = scopes["work_orders" if table == "work_orders" else "orders"]
        for row in tx.execute(f"SELECT id,source_json FROM {table} ORDER BY id"):
            key = source_key(json.loads(row["source_json"]))
            if key in seen:
                raise ValueError("canonical source identity collision: " + table + "/" + row["id"] + " conflicts with " + seen[key])
            seen[key] = table + "/" + row["id"]
            updates.append((table, key, row["id"]))
    # All domains preflight before the first update. Caller owns one transaction,
    # including prior schema upgrades, so any error rolls the entire upgrade back.
    for table, key, ident in updates:
        tx.execute(f"UPDATE {table} SET source_system=?,source_type=?,source_external_id=? WHERE id=?", (*key, ident))
