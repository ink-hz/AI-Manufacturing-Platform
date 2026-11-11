NATIVE_MATERIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS mes_order_bindings(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), work_order_id TEXT NOT NULL REFERENCES work_orders(id), namespace TEXT NOT NULL, shop_order TEXT NOT NULL, environment TEXT NOT NULL, site_code TEXT NOT NULL, verified_at TEXT NOT NULL, actor_id TEXT NOT NULL, request_ids_json TEXT NOT NULL, active INTEGER NOT NULL, superseded_by TEXT REFERENCES mes_order_bindings(id), reason TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS mes_binding_work_order ON mes_order_bindings(work_order_id) WHERE active=1;
CREATE UNIQUE INDEX IF NOT EXISTS mes_binding_source ON mes_order_bindings(namespace,shop_order) WHERE active=1;
CREATE TABLE IF NOT EXISTS mes_material_snapshots(id TEXT PRIMARY KEY, binding_id TEXT NOT NULL REFERENCES mes_order_bindings(id), collected_at TEXT NOT NULL, total INTEGER NOT NULL, request_ids_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mes_material_components(snapshot_id TEXT NOT NULL REFERENCES mes_material_snapshots(id), position INTEGER NOT NULL, component_key TEXT NOT NULL, material_id TEXT NOT NULL, required_quantity TEXT NOT NULL, withdrawn_quantity TEXT, unit TEXT NOT NULL, storage_location TEXT, PRIMARY KEY(snapshot_id,position), UNIQUE(snapshot_id,component_key));
"""
