"""Run in a new interpreter with the separately pinned original A1 source."""

import json
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manufacturing_platform import build_workflow_router
import manufacturing_platform

config = json.loads(Path(sys.argv[1]).read_text())
root = Path(config["database_root"])
app = FastAPI()
app.include_router(build_workflow_router(
    database_path=str(root / "domain.db"), authority_database_path=str(root / "authority.db"),
    assets_dir=str(root), authenticate=lambda request, write=False: config["actor"],
    resolve_subject=lambda uid: str(uid) == config["actor"]["user_id"],
    release="historical-A1", dataset=config["dataset"],
))
with TestClient(app) as client:
    response = client.post("/api/v1/manufacturing/workflow/projects", json=config["body"])
    assert response.status_code == 200, response.text
    for index, demand in enumerate(config.get("demands", [])):
        created = client.post("/api/v1/manufacturing/workflow/projects/" + response.json()["id"] + "/commands", json={
            **demand, "expected_version": index + 1,
        })
        assert created.status_code == 200, created.text
Path(sys.argv[2]).write_text(json.dumps({"source_file": manufacturing_platform.__file__, "status": response.status_code, "result": response.json()}))
