"""Disposable loopback host of the actual PF create_app, never packaged."""

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from contextlib import asynccontextmanager
from ipaddress import ip_address

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scenarios.base import owned_run
from scenarios.provenance import checked_files
from d3.pf_identity import NoObservationGrants, SyntheticIdentity
from app.control_plane.authorization import AuthorizationService
from app.main import create_app


def loopback_certificate(root):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable D3 loopback")])
    now = datetime.now(UTC)
    certificate = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]), critical=False).sign(key, hashes.SHA256())
    cert, private = root / "loopback-cert.pem", root / "loopback-key.pem"
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    return cert, private


def serve(root):
    manifest = owned_run(root)
    fixture = root / "pf-fixture.json"
    if fixture.is_symlink() or fixture.stat().st_mode & 0o077:
        raise ValueError("Private fixture secret permissions required")
    config = json.loads(fixture.read_text())
    if config["dataset_mode"] != "test" or config["dataset_id"] != manifest["dataset_id"]:
        raise ValueError("Only explicitly owned isolated test datasets allowed")
    for name in ("workflow.db", "authority.db", "legacy.db", "identity-control.json", "manifest.json"):
        if (root / name).is_symlink():
            raise ValueError("Symlink dataset refused")
    source = manifest["source"]
    pfroot = Path(config["platform_root"])
    if source["provenance_kind"] == "pinned_export":
        checked_files(pfroot, source["platform_runtime"]["files"])
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"https://127.0.0.1:{sock.getsockname()[1]}"
    cert, private = loopback_certificate(root)
    for name in tuple(os.environ):
        if name.startswith("PLATFORM_"):
            del os.environ[name]
    os.environ.update({
        "PLATFORM_AGENT_BRAIN_ENABLED": "0", "PLATFORM_STATIC_DIR": str(root / "static"),
        "PLATFORM_MANUFACTURING_ROOT": config["manufacturing_root"],
        "PLATFORM_MANUFACTURING_DATABASE_PATH": str(root / "legacy.db"),
        "PLATFORM_MANUFACTURING_WORKFLOW_DATABASE_PATH": str(root / "workflow.db"),
        "PLATFORM_MANUFACTURING_AUTHORITY_DATABASE_PATH": str(root / "authority.db"),
        "PLATFORM_MANUFACTURING_DATASET_ID": config["dataset_id"],
        "PLATFORM_MANUFACTURING_DATASET_MODE": "test",
        "PLATFORM_MANUFACTURING_DATASET_LABEL": "Simulated workflow acceptance",
    })
    if config["bootstrap"] == "disabled":
        for name in ("WORKFLOW_DATABASE_PATH", "AUTHORITY_DATABASE_PATH", "DATASET_ID", "DATASET_MODE", "DATASET_LABEL"):
            os.environ.pop("PLATFORM_MANUFACTURING_" + name)
    elif config["bootstrap"] == "unavailable":
        os.environ["PLATFORM_MANUFACTURING_ROOT"] = str(root / "absent-release")
    registry, contract = root / "registry.yaml", root / "contract.json"
    registry.write_text("version: 1\nagents: []\n")
    contract.write_text('{"bots": []}')
    auth = SyntheticIdentity(root, config, origin)
    clock = datetime.fromisoformat(config["business_clock"])
    app = create_app(registry_path=str(registry), cluster_contract_path=str(contract), start_poller=False, identity_auth=auth, identity_authorization=AuthorizationService(NoObservationGrants()), manufacturing_business_clock=(lambda: clock) if config["bootstrap"] == "enabled" else None)
    def record_runtime():
        private.unlink(missing_ok=True)
        files = {}
        for module in tuple(sys.modules.values()):
            filename = getattr(module, "__file__", None)
            if filename and Path(filename).is_file() and Path(filename).resolve().is_relative_to(pfroot.resolve()):
                path = Path(filename).resolve()
                files[str(path.relative_to(pfroot.resolve()))] = hashlib.sha256(path.read_bytes()).hexdigest()
        if source["provenance_kind"] == "pinned_export":
            pinned = source["platform_runtime"]["files"]
            if any(pinned.get(k) != v for k, v in files.items()):
                raise ValueError("Executed platform file missing from pinned provenance")
        (root / f"pf-loaded-{os.getpid()}.json").write_text(json.dumps({"root": str(pfroot), "files": files}, sort_keys=True))
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        try:
            async with original_lifespan(application) as state:
                yield state
        finally:
            record_runtime()
    app.router.lifespan_context = lifespan
    print(json.dumps({"port": sock.getsockname()[1]}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, ssl_certfile=str(cert), ssl_keyfile=str(private))).run(sockets=[sock])


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
