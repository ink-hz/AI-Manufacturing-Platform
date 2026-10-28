"""Owned real-PF process transport using real login/middleware and synthetic provider."""

import hashlib
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import secrets
import shutil
import select
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import NAMESPACE_URL, uuid5

from ..scenarios.base import ROOT, owned_run
from ..scenarios.fixtures import BusinessHTTP

PREFIX = "/_preview/dingtalk-r1"


class PlatformHTTP(BusinessHTTP):
    def __init__(self, context, *, bootstrap="enabled", package_source=None):
        self.bootstrap, self.package_source = bootstrap, package_source
        super().__init__(context)

    def start(self):
        manifest = owned_run(self.context.directory)
        source = manifest["source"]
        pfroot = source.get("platform_runtime", {}).get("root", source["roots"]["platform"])
        mfroot = source.get("manufacturing_runtime", {}).get("root", source["roots"]["manufacturing"])
        release = self.context.directory / ("pf-release-" + self.bootstrap)
        if not release.exists():
            shutil.copytree(Path(self.package_source or mfroot) / "src", release / "src", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(Path(mfroot) / "webui/dist", release / "webui/dist")
            (release / "docs").mkdir()
            document = release / "docs/manufacturing-system-handbook.md"
            shutil.copyfile(Path(mfroot) / "docs/manufacturing-system-handbook.md", document)
            from datetime import UTC, datetime
            (release / "handbook-metadata.json").write_text(json.dumps({"files": {"docs/manufacturing-system-handbook.md": {"sha256": hashlib.sha256(document.read_bytes()).hexdigest(), "updated_at": datetime.now(UTC).isoformat()}}}))
            files = {str(p.relative_to(release)): hashlib.sha256(p.read_bytes()).hexdigest() for p in release.rglob("*") if p.is_file()}
            for name, digest in files.items():
                expected = source["files"].get(name, source["build_files"].get(name))
                if name != "handbook-metadata.json" and not (self.package_source and name.startswith("src/")):
                    assert expected == digest, "Private PF release differs from bound source: " + name
            self.context.evidence.record("pf-manufacturing-release", {"root": str(release), "files": files, "bootstrap": self.bootstrap, "source_override": str(self.package_source) if self.package_source else None, "historical_assets_claim": "none; shared current assets are loader prerequisites only" if self.package_source else "current exact build"})
            for p in release.rglob("*"):
                p.chmod(0o555 if p.is_dir() else 0o444)
            release.chmod(0o555)
        mfroot = str(release)
        self.secret = secrets.token_urlsafe(32)
        fixture = self.context.directory / "pf-fixture.json"
        fixture.write_text(json.dumps({
            "secret": self.secret, "seed": self.context.seed,
            "business_clock": self.context.clock.isoformat(),
            "dataset_mode": "test", "dataset_id": self.context.dataset_id,
            "platform_root": pfroot, "manufacturing_root": mfroot,
            "bootstrap": self.bootstrap,
        }))
        fixture.chmod(0o600)
        control = self.context.directory / "identity-control.json"
        if not control.exists():
            control.write_text(json.dumps({name: {"role": "platform_owner" if name == "owner" else "platform_admin" if name == "admin" else "management_viewer" if name == "viewer" else "member"} for name in ("owner", "engineering", "planner", "supply", "production", "quality", "warehouse", "outsider", "admin", "viewer")}))
            control.chmod(0o600)
        static = self.context.directory / "static"
        static.mkdir(exist_ok=True)
        (static / "index.html").write_text('<html><head></head><body>Disposable synthetic host</body></html>')
        self.log = (self.context.directory / f"pf-host-{time.time_ns()}.log").open("x")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PLATFORM_")}
        # No employee session or external-service configuration is inherited.
        env.update(PYTHONPATH=str(Path(pfroot) / "backend") + os.pathsep + self.context.business_source_root, PYTHONDONTWRITEBYTECODE="1")
        self.process = subprocess.Popen([sys.executable, str(ROOT / "tests/workflow/d3/pf_host.py"), str(self.context.directory)], env=env, cwd=self.context.directory, stdout=subprocess.PIPE, stderr=self.log, text=True)
        ready, _, _ = select.select([self.process.stdout], [], [], 15)
        if not ready:
            self.close()
            raise RuntimeError("PF host startup timeout")
        line = self.process.stdout.readline()
        if not line:
            self.close()
            raise RuntimeError("PF host exited before binding; see private stderr")
        self.base = f"https://127.0.0.1:{json.loads(line)['port']}"
        self.tls = ssl.create_default_context(cafile=str(self.context.directory / "loopback-cert.pem"))
        deadline = time.monotonic() + 15
        while True:
            try:
                self.login("owner")
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode()
                self.close()
                raise RuntimeError(f"PF login rejected: {exc.code} {detail}") from exc
            except urllib.error.URLError:
                if time.monotonic() >= deadline:
                    self.close()
                    raise RuntimeError("PF host readiness timeout")
                time.sleep(0.025)
        fixture.unlink()

    def close(self):
        super().close()
        (self.context.directory / "pf-fixture.json").unlink(missing_ok=True)

    def login(self, actor):
        response = urllib.request.urlopen(urllib.request.Request(
            self.base + PREFIX + "/api/v1/auth/dingtalk/in-client/exchange",
            data=json.dumps({"code": self.secret + ":" + actor}).encode(),
            headers={"content-type": "application/json", "origin": self.base},
        ), timeout=10, context=self.tls)
        body = json.load(response)
        cookies = SimpleCookie()
        for value in response.headers.get_all("Set-Cookie", []):
            cookies.load(value)
        assert cookies["platform_preview_session"]["httponly"] and cookies["platform_preview_session"]["secure"]
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.tls))
        # Genuine secure cookies are sent only to this certificate-verified
        # loopback HTTPS origin; production cookie policy stays unchanged.
        opener.addheaders = [("Cookie", "; ".join(f"{k}={v.value}" for k, v in cookies.items()))]
        identity = {"user_id": str(uuid5(NAMESPACE_URL, f"fixture:{self.context.seed}:{actor}")), "display_name": actor}
        self.sessions[actor] = (opener, body["csrf_token"], identity)
        self.context.evidence.record("pf-login", {"actor": identity, "pid": self.process.pid, "provider": "synthetic-test-only", "route": PREFIX + "/api/v1/auth/dingtalk/in-client/exchange", "secure_cookie": True, "cookie_sha256": hashlib.sha256(cookies["platform_preview_session"].value.encode()).hexdigest()})
        return identity

    def request(self, method, path, *, actor="owner", body=None, expected=200, headers=None, anonymous=False):
        if not anonymous and actor not in self.sessions:
            self.login(actor)
        opener, csrf, identity = (urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.tls)), "", None) if anonymous else self.sessions[actor]
        hs = {"content-type": "application/json", "origin": self.base, "x-csrf-token": csrf, **(headers or {})}
        artifact = self.context.evidence.record_request({"method": method, "path": PREFIX + path, "actor": identity, "headers": hs, "body": body, "host_pid": self.process.pid})
        try:
            response = opener.open(urllib.request.Request(self.base + PREFIX + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers=hs), timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        status, text = response.code, response.read().decode()
        try:
            value = json.loads(text)
        except ValueError:
            value = text
        self.context.evidence.record_response({"request_artifact": str(artifact), "status": status, "headers": dict(response.headers), "body": value})
        assert status in (expected if isinstance(expected, tuple) else (expected,)), f"{method} {path}: expected {expected}, received {status}: {text}"
        return value

    def control(self, actor, **values):
        path = self.context.directory / "identity-control.json"
        state = json.loads(path.read_text())
        state[actor].update(values)
        path.write_text(json.dumps(state))
        self.context.evidence.record("synthetic-provider-state", {"actor": actor, **values})

    def restart(self):
        prior_pid = self.process.pid
        old_cookie = self.sessions["owner"][0].addheaders[0][1]
        super().restart()
        assert self.process.pid != prior_pid
        self.get("/access", headers={"Cookie": old_cookie}, expected=401)
        self.context.evidence.record("pf-fresh-process", {"prior_pid": prior_pid, "new_pid": self.process.pid, "prior_cookie_denied": True})

    def authority(self, action, **fields):
        from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter
        from manufacturing_platform.workflow.exchange_models import ExternalRequest
        adapter = MockAuthorityAdapter(str(self.paths.authority), self.context.dataset_id, business_clock=lambda: self.context.clock)
        request = self.context.evidence.record("authority-request", {"action": action, "fields": fields, "boundary": "stateful external adapter"})
        result = adapter.submit(ExternalRequest.model_validate(fields["request"])) if action == "submit" else getattr(adapter, action)(**fields)
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        self.context.evidence.record("authority-response", {"request": str(request), "value": result})
        return result
