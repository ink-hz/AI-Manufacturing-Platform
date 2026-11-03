"""Schema23 is additive and contains no source facts or readiness seed."""

INTEGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_integration_profiles(
 project_id TEXT PRIMARY KEY REFERENCES projects(id),
 profile TEXT NOT NULL CHECK(profile IN ('legacy-erp-v1','oem-network-v1'))
);
CREATE TRIGGER IF NOT EXISTS project_profile_immutable_insert BEFORE INSERT ON project_integration_profiles
WHEN EXISTS(SELECT 1 FROM project_integration_profiles WHERE project_id=NEW.project_id)
BEGIN SELECT RAISE(ABORT, 'immutable project integration profile'); END;
CREATE TRIGGER IF NOT EXISTS project_profile_immutable_update BEFORE UPDATE ON project_integration_profiles
BEGIN SELECT RAISE(ABORT, 'immutable project integration profile'); END;
CREATE TRIGGER IF NOT EXISTS project_profile_immutable_delete BEFORE DELETE ON project_integration_profiles
BEGIN SELECT RAISE(ABORT, 'immutable project integration profile'); END;
CREATE TABLE IF NOT EXISTS integration_intents(
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES projects(id),
 actor_id TEXT NOT NULL,
 system TEXT NOT NULL,
 operation TEXT NOT NULL,
 policy_action TEXT NOT NULL,
 expected_version INTEGER NOT NULL CHECK(expected_version>=1),
 payload_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('prepared','pending','unknown','accepted','rejected','applied')),
 created_at TEXT NOT NULL,
 UNIQUE(project_id,id)
);
CREATE TRIGGER IF NOT EXISTS integration_intent_immutable_insert BEFORE INSERT ON integration_intents
WHEN EXISTS(SELECT 1 FROM integration_intents WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT, 'immutable integration intent identity'); END;
CREATE TRIGGER IF NOT EXISTS integration_intent_immutable_delete BEFORE DELETE ON integration_intents
BEGIN SELECT RAISE(ABORT, 'immutable integration intent identity'); END;
CREATE TRIGGER IF NOT EXISTS integration_intent_identity_immutable
BEFORE UPDATE OF id,project_id,actor_id,system,operation,policy_action,expected_version,payload_json,payload_hash,created_at ON integration_intents
BEGIN SELECT RAISE(ABORT, 'immutable integration intent identity'); END;
CREATE INDEX IF NOT EXISTS integration_intents_project ON integration_intents(project_id,created_at,id);
CREATE TABLE IF NOT EXISTS integration_receipts(
 project_id TEXT NOT NULL REFERENCES projects(id),
 intent_id TEXT NOT NULL,
 attempt INTEGER NOT NULL CHECK(attempt>=1),
 receipt_json TEXT NOT NULL,
 received_at TEXT NOT NULL,
 PRIMARY KEY(project_id,intent_id,attempt),
 FOREIGN KEY(project_id,intent_id) REFERENCES integration_intents(project_id,id)
);
CREATE TABLE IF NOT EXISTS integration_projections(
 project_id TEXT NOT NULL REFERENCES projects(id),
 system TEXT NOT NULL,
 object_type TEXT NOT NULL,
 external_id TEXT NOT NULL,
 version INTEGER NOT NULL CHECK(version>=1),
 payload_hash TEXT NOT NULL,
 fact_json TEXT NOT NULL,
 result_json TEXT NOT NULL,
 projected_at TEXT NOT NULL,
 PRIMARY KEY(project_id,system,object_type,external_id,version)
);
CREATE TABLE IF NOT EXISTS integration_object_links(
 project_id TEXT NOT NULL REFERENCES projects(id),
 system TEXT NOT NULL,
 object_type TEXT NOT NULL,
 external_id TEXT NOT NULL,
 version INTEGER NOT NULL,
 target_kind TEXT NOT NULL,
 target_id TEXT NOT NULL,
 relation TEXT NOT NULL,
 PRIMARY KEY(project_id,system,object_type,external_id,version,target_kind,target_id,relation),
 FOREIGN KEY(project_id,system,object_type,external_id,version)
 REFERENCES integration_projections(project_id,system,object_type,external_id,version)
);
CREATE INDEX IF NOT EXISTS integration_links_target ON integration_object_links(project_id,target_kind,target_id);
"""


# Mutable transport scheduling only; independent of immutable intent/fact identity.
NETWORK_SCHEDULER_SCHEMA = """
CREATE TABLE IF NOT EXISTS integration_network_cursors(
 project_id TEXT NOT NULL REFERENCES projects(id),
 producer TEXT NOT NULL,
 position INTEGER NOT NULL CHECK(position>=1),
 turn INTEGER NOT NULL CHECK(turn>=1),
 PRIMARY KEY(project_id,producer)
)
"""
INTEGRATION_SCHEMA += NETWORK_SCHEDULER_SCHEMA + ";\n"


def migrate_integration_schema(tx):
    # sqlite executescript implicitly commits, so use complete statements within
    # the caller's existing migration transaction (including trigger bodies).
    from sqlite3 import complete_statement

    statement = ""
    for line in INTEGRATION_SCHEMA.splitlines(keepends=True):
        statement += line
        if complete_statement(statement):
            tx.execute(statement)
            statement = ""
