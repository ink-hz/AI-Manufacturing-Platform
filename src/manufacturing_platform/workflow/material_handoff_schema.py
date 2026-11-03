"""Additive schema22: manual handoffs, separate from engineering handoffs."""

HANDOFF_SCHEMA = """
CREATE TABLE IF NOT EXISTS material_handoffs(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 id TEXT NOT NULL UNIQUE,
 project_id TEXT NOT NULL REFERENCES projects(id),
 material_lot_id TEXT NOT NULL REFERENCES material_lots(id),
 work_order_id TEXT REFERENCES work_orders(id),
 sender_id TEXT NOT NULL,
 receiver_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','received','disputed','resolved','cancelled')),
 payload_json TEXT NOT NULL,
 receipt_json TEXT,
 resolution_json TEXT,
 cancellation_json TEXT
);
CREATE INDEX IF NOT EXISTS material_handoffs_page ON material_handoffs(project_id,seq);
CREATE INDEX IF NOT EXISTS material_handoffs_receiver ON material_handoffs(project_id,receiver_id,state,seq);
CREATE INDEX IF NOT EXISTS material_handoffs_sender ON material_handoffs(project_id,sender_id,state,seq);
"""
