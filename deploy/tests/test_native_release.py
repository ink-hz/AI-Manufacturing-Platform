import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import release
import release_guard
from test_release_upgrade import fixture as upgrade_fixture

PROFILE = "native-production-tools-sdk-v1"
PINS = {
    "PyMySQL": "1.2.4",
    "oss2": "2.19.1",
    "crcmod": "1.7",
    "pycryptodome": "4.4.0",
    "aliyun-python-sdk-kms": "2.16.5",
    "aliyun-python-sdk-core": "2.16.1",
}
PACKAGES = ["pymysql", "oss2", "crcmod", "Crypto", "aliyunsdkcore", "aliyunsdkkms"]
NATIVE = {
    "config_path": "/app/data/manufacturing/native-production-tools/config.json",
    "snapshot_path": "/app/data/manufacturing/native-production-tools/snapshots.sqlite3",
}


def sdk(tmp_path):
    root = tmp_path / "build/native-sdk"
    root.mkdir(parents=True)
    for package in PACKAGES:
        path = root / package / "__init__.py"
        path.parent.mkdir()
        path.write_text("# synthetic SDK package\n")
    for name, version in PINS.items():
        info = root / (name.lower().replace("-", "_") + "-" + version + ".dist-info")
        info.mkdir()
        (info / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: " + name + "\nVersion: " + version + "\n"
        )
    manifest = {
        "profile": PROFILE,
        "python": "3.11",
        "platform": "linux-x86_64",
        "distributions": PINS.copy(),
        "files": {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*")
            if p.is_file()
        },
    }
    request = {"native_sdk": {"profile": PROFILE, "manifest_sha256": ""}}
    pin(tmp_path, request, manifest)
    return root, manifest, request


def pin(stage, request, manifest):
    path = stage / "build/native-sdk-manifest.json"
    path.write_text(json.dumps(manifest))
    request["native_sdk"]["manifest_sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def helper():
    import native_release

    return native_release


def test_profile_validates_exact_manifest_tree_and_default_dockerfile(tmp_path):
    _root, manifest, request = sdk(tmp_path)
    native = helper()
    assert native.validate_sdk(tmp_path, request) == manifest
    default = "FROM baseline:fixed\nCOPY --chown=10001:10001 backend/ /app/backend/app/\nCOPY --chown=10001:10001 static/ /app/backend/app/static/\n"
    assert native.dockerfile("baseline:fixed", {}) == default
    assert native.dockerfile("baseline:fixed", request) == default.replace(
        "\nCOPY --chown=10001:10001 backend/",
        "\nCOPY --chown=0:0 native-sdk/ /usr/local/lib/python3.11/site-packages/\nCOPY --chown=10001:10001 backend/",
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m.update(extra="forbidden"),
        lambda m: m.update(python="3.12"),
        lambda m: m.update(platform="darwin-arm64"),
        lambda m: m["distributions"].update(oss2="latest"),
        lambda m: m["files"].update({"../escape": "a" * 64}),
        lambda m: m["files"].update({"pymysql/__pycache__/bad.pyc": "a" * 64}),
        lambda m: m["files"].update({"requests/__init__.py": "a" * 64}),
        lambda m: m["files"].update({"pymysql/secret.json": "not-a-hash"}),
    ],
)
def test_invalid_manifests_rejected(tmp_path, change):
    _root, manifest, request = sdk(tmp_path)
    change(manifest)
    pin(tmp_path, request, manifest)
    with pytest.raises(ValueError):
        helper().validate_sdk(tmp_path, request)


@pytest.mark.parametrize(
    "change",
    [
        lambda r, q: q["native_sdk"].update(extra=True),
        lambda r, q: q["native_sdk"].update(profile="other"),
        lambda r, q: q["native_sdk"].update(manifest_sha256="0" * 64),
        lambda r, q: (r / "pymysql/__init__.py").write_text("changed"),
        lambda r, q: (r / "unknown").mkdir(),
        lambda r, q: (r / "pymysql/empty").mkdir(),
        lambda r, q: (r / "pymysql/link").symlink_to("/etc/passwd"),
    ],
)
def test_unpinned_or_uninventoried_payload_rejected(tmp_path, change):
    root, _manifest, request = sdk(tmp_path)
    change(root, request)
    with pytest.raises(ValueError):
        helper().validate_sdk(tmp_path, request)


def test_baseline_check_rejects_namespace_collision_and_is_read_only(tmp_path):
    _root, manifest, _request = sdk(tmp_path)
    native = helper()
    site = tmp_path / "site"
    site.mkdir()
    native.validate_baseline_sdk(manifest, site)
    (site / "Crypto").mkdir()
    with pytest.raises(ValueError, match="baseline_sdk_collision"):
        native.validate_baseline_sdk(manifest, site)
    assert (site / "Crypto").is_dir()


def test_installed_check_reads_actual_files_metadata_and_imports(tmp_path):
    root, manifest, _request = sdk(tmp_path)
    native = helper()
    script = (
        Path(native.__file__).read_text()
        + '\nsys.platform="linux";platform.machine=lambda:"x86_64"\nverify_installed_sdk(json.loads(sys.argv[1]),Path(sys.argv[2]))\n'
    )
    # Separate interpreter excludes developer-installed SDK imports and bytecode writes.
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, json.dumps(manifest), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    (root / "oss2/__init__.py").write_text("changed")
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, json.dumps(manifest), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "installed_sdk_hash" in result.stderr


def test_native_environment_is_exact_opt_in_and_preserved():
    base = {
        "platform_commit": "a" * 40,
        "manufacturing_commit": "b" * 40,
        "expected_old_platform_commit": "c" * 40,
        "expected_old_manufacturing_commit": "d" * 40,
    }
    native = helper()
    assert native.native_configuration(base) is None
    request = {**base, "target_native": NATIVE}
    assert native.native_configuration(request) == NATIVE
    assert (
        release.environment_delta(request)[native.NATIVE_FIELDS["config_path"]]
        == NATIVE["config_path"]
    )
    assert not set(native.NATIVE_FIELDS.values()) & set(
        release.baseline_environment(request)
    )
    request["baseline_native"] = NATIVE
    assert native.native_configuration(request, baseline=True) == NATIVE
    for value in [
        {**NATIVE, "extra": "bad"},
        {**NATIVE, "config_path": "/tmp/config.json"},
        None,
    ]:
        with pytest.raises(ValueError):
            native.native_configuration({**request, "target_native": value})


def test_compose_native_opt_in_adds_only_two_fixed_paths():
    native = helper()
    before, after, options = upgrade_fixture()
    env = native.native_environment(NATIVE)
    after["services"]["platform-api"]["environment"].update(env)
    options["environment_delta"].update(env)
    with pytest.raises(ValueError):
        release_guard.validate_upgrade_candidate(before, after, **options)
    release_guard.validate_upgrade_candidate(
        before, after, native_enabled=True, **options
    )
    before["services"]["platform-api"]["environment"].update(env)
    options["baseline_environment"].update(env)
    release_guard.validate_upgrade_candidate(
        before, after, native_enabled=True, **options
    )
    options["environment_delta"][native.NATIVE_FIELDS["snapshot_path"]] = "/tmp/other"
    with pytest.raises(ValueError):
        release_guard.validate_upgrade_candidate(
            before, after, native_enabled=True, **options
        )


def test_private_storage_rejects_permissions_symlinks_and_database_hardlinks(
    tmp_path, monkeypatch
):
    native = helper()
    directory = tmp_path / "native-production-tools"
    directory.mkdir(mode=0o700)
    config = directory / "config.json"
    config.write_text("private example")
    config.chmod(0o600)
    real = native.trusted_stat

    def owned(path):
        info = real(path)
        fields = list(info)
        fields[4] = 10001
        fields[5] = 10001
        import os

        return os.stat_result(fields)

    monkeypatch.setattr(native, "trusted_stat", owned)
    request = {"target_native": NATIVE, "data_host": str(tmp_path)}
    result = native.validate_native_storage(request)
    assert result["native_config"] == hashlib.sha256(config.read_bytes()).hexdigest()
    config.chmod(0o644)
    with pytest.raises(ValueError):
        native.validate_native_storage(request)
    config.chmod(0o600)
    database = tmp_path / "workbench.sqlite3"
    database.write_bytes(b"isolated")
    snapshot = directory / "snapshots.sqlite3"
    snapshot.hardlink_to(database)
    with pytest.raises(ValueError, match="native_storage_inode_alias"):
        native.validate_native_storage(request)
    snapshot.unlink()
    snapshot.symlink_to(database)
    with pytest.raises(ValueError):
        native.validate_native_storage(request)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda site: (site / "pymysql.py").write_text("existing namespace"),
        lambda site: (site / "PyMySQL-1.2.4.dist-info").mkdir(),
    ],
)
def test_baseline_rejects_alternate_namespace_or_metadata_spellings(tmp_path, mutation):
    _root, manifest, _request = sdk(tmp_path)
    site = tmp_path / "existing"
    site.mkdir()
    mutation(site)
    with pytest.raises(ValueError):
        helper().validate_baseline_sdk(manifest, site)


def test_installed_check_rejects_wrong_runtime_versions_and_broken_imports(
    tmp_path, monkeypatch
):
    root, manifest, _request = sdk(tmp_path)
    native = helper()
    with pytest.raises(ValueError, match="installed_sdk_runtime"):
        monkeypatch.setattr(native.sys, "platform", "not-linux")
        native.verify_installed_sdk(manifest, root)
    monkeypatch.undo()
    metadata = root / "pymysql-1.2.4.dist-info/METADATA"
    metadata.write_text("Name: PyMySQL\nVersion: 9.0\n")
    manifest["files"][metadata.relative_to(root).as_posix()] = hashlib.sha256(
        metadata.read_bytes()
    ).hexdigest()
    script = (
        Path(native.__file__).read_text()
        + '\nsys.platform="linux";platform.machine=lambda:"x86_64"\nverify_installed_sdk(json.loads(sys.argv[1]),Path(sys.argv[2]))\n'
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, json.dumps(manifest), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "installed_sdk_versions" in result.stderr
    metadata.write_text("Name: PyMySQL\nVersion: 1.2.4\n")
    manifest["files"][metadata.relative_to(root).as_posix()] = hashlib.sha256(
        metadata.read_bytes()
    ).hexdigest()
    package = root / "oss2/__init__.py"
    package.write_text('raise RuntimeError("broken SDK import")\n')
    manifest["files"][package.relative_to(root).as_posix()] = hashlib.sha256(
        package.read_bytes()
    ).hexdigest()
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, json.dumps(manifest), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "broken SDK import" in result.stderr


def test_exact_dockerfile_guard_rejects_generic_operations_with_and_without_profile(
    tmp_path,
):
    _root, _manifest, request = sdk(tmp_path)
    native = helper()
    for spec in [{}, request]:
        expected = native.dockerfile("baseline", spec)
        native.validate_dockerfile(expected, "baseline", spec)
        for extra in [
            "RUN pip install oss2\n",
            "USER root\n",
            "ENV KEY=value\n",
            "COPY other/ /app/\n",
        ]:
            with pytest.raises(ValueError, match="copy_only_dockerfile_required"):
                native.validate_dockerfile(expected + extra, "baseline", spec)
    with pytest.raises(ValueError):
        native.validate_dockerfile(
            native.dockerfile("baseline", request), "baseline", {}
        )


def test_container_probe_uses_pinned_manifest_and_readonly_python(tmp_path):
    _root, manifest, _request = sdk(tmp_path)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))

    helper().check_container_sdk(run, "baseline-container", manifest, baseline=True)
    args, kwargs = calls[0]
    assert args[:9] == [
        "docker",
        "exec",
        "-i",
        "--user",
        "10001:10001",
        "baseline-container",
        "python",
        "-B",
        "-c",
    ]
    assert args[9].endswith("validate_baseline_sdk(json.load(sys.stdin))\n")
    assert json.loads(kwargs["data"]) == manifest


def test_private_extraction_normalizes_only_validated_sdk_copy_metadata(
    tmp_path, monkeypatch
):
    root, manifest, request = sdk(tmp_path)
    native = helper()
    private = tmp_path / "operator.private"
    private.write_text("private")
    private.chmod(0o600)
    for path in [root, *root.rglob("*")]:
        path.chmod(0o700 if path.is_dir() else 0o600)
    real = native.trusted_stat

    def root_owned(path):
        info = real(path)
        fields = list(info)
        fields[4] = fields[5] = 0
        import os

        return os.stat_result(fields)

    monkeypatch.setattr(native, "trusted_stat", root_owned)
    native.normalize_sdk_copy(tmp_path, request)
    native.validate_sdk_copy_metadata(tmp_path, request)
    import stat

    assert all(
        stat.S_IMODE(path.stat().st_mode) == (0o755 if path.is_dir() else 0o644)
        for path in [root, *root.rglob("*")]
    )
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    assert native.validate_sdk(tmp_path, request) == manifest
    (root / "pymysql/__init__.py").write_text("changed")
    (root / "pymysql/__init__.py").chmod(0o600)
    with pytest.raises(ValueError):
        native.normalize_sdk_copy(tmp_path, request)
    assert stat.S_IMODE((root / "pymysql/__init__.py").stat().st_mode) == 0o600


def test_sdk_metadata_versions_validated_before_build(tmp_path):
    root, manifest, request = sdk(tmp_path)
    metadata = root / "pymysql-1.2.4.dist-info/METADATA"
    metadata.write_text("Name: PyMySQL\nVersion: 9.0\n")
    manifest["files"][metadata.relative_to(root).as_posix()] = hashlib.sha256(
        metadata.read_bytes()
    ).hexdigest()
    pin(tmp_path, request, manifest)
    with pytest.raises(ValueError, match="sdk_versions"):
        helper().validate_sdk(tmp_path, request)


def test_snapshot_rejects_hardlink_to_database_sidecar(tmp_path, monkeypatch):
    import os

    native = helper()
    directory = tmp_path / "native-production-tools"
    directory.mkdir(mode=0o700)
    config = directory / "config.json"
    config.write_text("example")
    config.chmod(0o600)
    wal = tmp_path / "workbench.sqlite3-wal"
    wal.write_bytes(b"production WAL")
    wal.chmod(0o600)
    (directory / "snapshots.sqlite3").hardlink_to(wal)
    real = native.trusted_stat

    def owned(path):
        fields = list(real(path))
        fields[4] = fields[5] = 10001
        return os.stat_result(fields)

    monkeypatch.setattr(native, "trusted_stat", owned)
    with pytest.raises(ValueError, match="native_snapshot_metadata"):
        native.validate_native_storage(
            {"target_native": NATIVE, "data_host": str(tmp_path)}
        )


def test_sdk_functional_crc_allows_upstream_python_implementation(tmp_path):
    root, manifest, _request = sdk(tmp_path)
    native = helper()
    files = {
        "crcmod/predefined.py": "def mkPredefinedCrcFun(name):\n    assert name=='crc-64'\n    return lambda value: 0x46A5A9388A5BEFFE\n",
        "Crypto/Cipher/__init__.py": "",
        "Crypto/Cipher/AES.py": "MODE_ECB=1\nclass Cipher:\n    def encrypt(self,value):return b'0'*16\ndef new(key,mode):return Cipher()\n",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content)
        manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    script = (
        Path(native.__file__).read_text()
        + '\nsys.platform="linux";platform.machine=lambda:"x86_64"\nSITE=Path(sys.argv[2]);verify_installed_sdk(json.loads(sys.argv[1]),SITE)\n'
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, json.dumps(manifest), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    path = root / "crcmod/predefined.py"
    path.write_text(files["crcmod/predefined.py"].replace("0x46A5A9388A5BEFFE", "0"))
    manifest["files"]["crcmod/predefined.py"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, json.dumps(manifest), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "installed_sdk_crc64" in result.stderr
