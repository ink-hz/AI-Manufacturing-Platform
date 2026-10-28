"""Private real HTTP/session transport and authorized domain prerequisites."""

import http.cookiejar
import json
import os
import secrets
import select
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .base import ROOT

BASE = "/api/v1/manufacturing/workflow"


class Response:
    def __init__(self, status, content):
        self.status_code, self.text = status, content

    def json(self):
        return json.loads(self.text)


class BusinessHTTP:
    def __init__(self, context):
        self.context, self.paths = context, context.paths
        self.sessions = {}
        self.start()

    def start(self):
        self.secret = secrets.token_urlsafe(32)
        path = self.context.directory / "fixture.json"
        path.write_text(
            json.dumps(
                {
                    "secret": self.secret,
                    "seed": self.context.seed,
                    "assets_dir": getattr(self.context, "ui_assets", None),
                    "business_clock": self.context.clock.isoformat(),
                    "dataset_id": self.context.dataset_id,
                    "dataset_label": "Simulated workflow acceptance",
                }
            )
        )
        path.chmod(0o600)
        self.log = (self.context.directory / f"host-{time.time_ns()}.log").open("x")
        env = {
            **os.environ,
            "PYTHONPATH": self.context.business_source_root,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tests/workflow/http_app.py"),
                str(self.context.directory),
            ],
            env=env,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
        )
        ready, _, _ = select.select([self.process.stdout], [], [], 15)
        if not ready:
            self.close()
            raise RuntimeError("HTTP host startup timeout")
        line = self.process.stdout.readline()
        if not line:
            self.close()
            raise RuntimeError("HTTP host exited before binding")
        self.base = f"http://127.0.0.1:{json.loads(line)['port']}"
        deadline = time.monotonic() + 15
        while True:
            try:
                self.login("owner")
                break
            except urllib.error.URLError:
                if time.monotonic() >= deadline:
                    self.close()
                    raise RuntimeError("HTTP host readiness timeout")
                time.sleep(0.025)
        path.unlink()

    def close(self):
        if getattr(self, "process", None) and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if getattr(self, "process", None) and self.process.stdout:
            self.process.stdout.close()
        if getattr(self, "log", None):
            self.log.close()
        (self.context.directory / "fixture.json").unlink(missing_ok=True)

    def restart(self):
        self.close()
        self.sessions.clear()
        self.start()
        self.context.evidence.record(
            "restart", {"fresh_process": self.process.pid, "fresh_sessions": True}
        )

    def login(self, actor):
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        response = opener.open(
            urllib.request.Request(
                self.base + "/fixture/login",
                data=json.dumps({"name": actor, "secret": self.secret}).encode(),
                headers={"content-type": "application/json"},
            ),
            timeout=10,
        )
        body = json.load(response)
        self.sessions[actor] = (opener, body["csrf"], body["identity"])
        self.context.evidence.record(
            "identity",
            {
                "actor": actor,
                "identity": body["identity"],
                "boundary": "test-only session provider",
            },
        )
        return body["identity"]

    def request(
        self,
        method,
        path,
        *,
        actor="owner",
        body=None,
        expected=200,
        headers=None,
        anonymous=False,
    ):
        if not anonymous and actor not in self.sessions:
            self.login(actor)
        opener, csrf, identity = (
            (urllib.request.build_opener(), "", None)
            if anonymous
            else self.sessions[actor]
        )
        hs = {
            "content-type": "application/json",
            "origin": self.base,
            "x-csrf-token": csrf,
        }
        hs.update(headers or {})
        request_artifact = self.context.evidence.record_request(
            {
                "method": method,
                "path": path,
                "actor": identity,
                "headers": hs,
                "body": body,
            }
        )
        request = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers=hs,
        )
        try:
            with opener.open(request, timeout=30) as response:
                result = Response(response.status, response.read().decode())
        except urllib.error.HTTPError as exc:
            result = Response(exc.code, exc.read().decode())
        self.context.evidence.record_response(
            {
                "request_artifact": str(request_artifact),
                "status": result.status_code,
                "body": result.json(),
            }
        )
        assert result.status_code == expected, (
            f"{method} {path}: expected {expected}, received {result.status_code}: {result.text}"
        )
        return result.json()

    def get(self, path, **kwargs):
        return self.request("GET", BASE + path, **kwargs)

    def post(self, path, body, **kwargs):
        return self.request("POST", BASE + path, body=body, **kwargs)

    def source(self, kind, label=None, version=1, **changes):
        at = self.context.clock.isoformat()
        return {
            "system": "acceptance-manual",
            "object_type": kind,
            "external_id": label or self.context.identifier(kind),
            "version": version,
            "mode": "manual",
            "occurred_at": at,
            "collected_at": at,
            "cutoff": at,
            "evidence": "Signed isolated simulated source",
            **changes,
        }

    def command(self, project, action, *, actor="owner", expected=200, **fields):
        version = self.get("/projects/" + project, actor=actor)["version"]
        operation = fields.pop("operation_id", self.context.identifier("operation"))
        body = {
            "operation_id": operation,
            "expected_version": version,
            "action": action,
            **fields,
        }
        result = self.post(
            f"/projects/{project}/commands", body, actor=actor, expected=expected
        )
        self.context.operation_ids.append(operation)
        if expected == 200 and "object_id" in result:
            self.context.object_ids.append(result["object_id"])
        return result

    def object(self, project, kind, ident):
        return self.get(f"/projects/{project}/objects/{kind}/{ident}")["value"]

    def objects(self, project, kind):
        items, offset = [], 0
        while True:
            page = self.get(
                f"/projects/{project}/objects/{kind}?limit=50&offset={offset}"
            )["items"]
            items.extend(page)
            if len(page) < 50:
                return items
            offset += 50

    def grant(self, project, actor, roles, qualifications=(), active=True):
        if actor not in self.sessions:
            self.login(actor)
        version = self.get("/projects/" + project)["version"]
        return self.request(
            "PUT",
            BASE + f"/projects/{project}/members/{self.sessions[actor][2]['user_id']}",
            body={
                "operation_id": self.context.identifier("grant"),
                "expected_version": version,
                "scope": {"kind": "project", "project_id": project},
                "roles": list(roles),
                "qualifications": list(qualifications),
                "active": active,
                "evidence": "Explicit isolated acceptance grant",
            },
        )

    def project(self, quantity="100", product="Camera", mode="internal", **contract):
        p = self.post(
            "/projects",
            {
                "operation_id": self.context.identifier("project"),
                "name": product + " acceptance",
                "line_id": self.context.identifier("line"),
                "product": product,
                "customer_id": "Customer 1",
                "mode": mode,
                "unit": {"code": "piece", "scale": 0},
                "quantity": str(quantity),
                "contract": {
                    "customer_approval_required": mode == "oem",
                    "customer_release_required": mode == "oem",
                    "acceptance_required": True,
                    "customer_revision": "C1",
                    "internal_revision": "M1",
                    "material_ownership_rules": "Customer 1 owns customer lots; manufacturer owns purchased lots",
                    **contract,
                },
            },
        )["id"]
        for actor, qualifications in [
            ("engineering", ["readiness_verification"]),
            ("planner", []),
            ("supply", []),
            ("production", []),
            ("quality", ["inspection", "disposition", "quality_release"]),
            ("warehouse", []),
        ]:
            self.grant(p, actor, [actor], qualifications)
        return p

    def authority(self, action, **fields):
        return self.request(
            "POST", "/fixture/authority", body={"action": action, "fields": fields}
        )

    def db(self):
        db = sqlite3.connect(f"file:{self.paths.domain}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return db


def connect(context):
    if context.client is None:
        context.client = BusinessHTTP(context)
    return context.client
