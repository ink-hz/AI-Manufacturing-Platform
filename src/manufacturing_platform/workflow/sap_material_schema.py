"""Local observations only; never a source-system command ledger."""
SAP_MATERIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS sap_material_observations(
 fingerprint TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('production-order','stock-requirements')),
 scope_json TEXT NOT NULL,
 refresh_seq INTEGER NOT NULL CHECK(refresh_seq>0),
 snapshot_json TEXT,
 refresh_error_json TEXT,
 PRIMARY KEY(fingerprint,kind,scope_json)
);
"""
