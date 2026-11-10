"""One explicit, offline COPY-only SDK profile and private native path checks."""

import hashlib
import importlib
import importlib.metadata
import json
import platform
import re
import stat
import sys
from pathlib import Path, PurePosixPath

PROFILE = "native-production-tools-sdk-v1"
# Reviewed Linux preparation: exactly 622 files; future trees require a new profile.
APPROVED_MANIFEST_SHA256 = (
    "e4e998c94b019b1d636fafead91e349b9bdbd00d6acff53be5dbf12856505517"
)
SITE = Path("/usr/local/lib/python3.11/site-packages")
PINS = {
    "PyMySQL": "1.2.4",
    "oss2": "2.19.1",
    "crcmod": "1.7",
    "pycryptodome": "4.4.0",
    "aliyun-python-sdk-kms": "2.16.5",
    "aliyun-python-sdk-core": "2.16.1",
}
PACKAGES = {"pymysql", "oss2", "crcmod", "Crypto", "aliyunsdkcore", "aliyunsdkkms"}
DIST_INFO = {
    name.lower().replace("-", "_") + "-" + version + ".dist-info"
    for name, version in PINS.items()
}
NATIVE_FIELDS = {
    "config_path": "PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_CONFIG_PATH",
    "snapshot_path": "PLATFORM_MANUFACTURING_PRODUCTION_TOOLS_SNAPSHOT_PATH",
}
NATIVE_PATHS = {
    "config_path": "/app/data/manufacturing/native-production-tools/config.json",
    "snapshot_path": "/app/data/manufacturing/native-production-tools/snapshots.sqlite3",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sdk_request(request):
    if "native_sdk" not in request:
        return None
    value = request["native_sdk"]
    require(
        isinstance(value, dict) and set(value) == {"profile", "manifest_sha256"},
        "native_sdk_exact_fields",
    )
    require(value["profile"] == PROFILE, "native_sdk_profile")
    require(
        isinstance(value["manifest_sha256"], str)
        and re.fullmatch("[0-9a-f]{64}", value["manifest_sha256"]),
        "native_sdk_manifest_pin",
    )
    require(
        value["manifest_sha256"] == APPROVED_MANIFEST_SHA256,
        "native_sdk_unapproved_manifest",
    )
    return value


def validate_manifest(manifest):
    require(
        isinstance(manifest, dict)
        and set(manifest)
        == {"profile", "python", "platform", "distributions", "files"},
        "native_sdk_manifest_fields",
    )
    require(
        manifest["profile"] == PROFILE
        and manifest["python"] == "3.11"
        and manifest["platform"] == "linux-x86_64",
        "native_sdk_runtime",
    )
    require(manifest["distributions"] == PINS, "native_sdk_distributions")
    files = manifest["files"]
    require(isinstance(files, dict) and files, "native_sdk_files")
    for name, value in files.items():
        require(isinstance(name, str), "native_sdk_path")
        path = PurePosixPath(name)
        require(
            not path.is_absolute()
            and len(path.parts) >= 2
            and path.as_posix() == name
            and ".." not in path.parts
            and "\\" not in name,
            "native_sdk_path",
        )
        require(
            path.parts[0] in PACKAGES | DIST_INFO
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"},
            "native_sdk_inventory",
        )
        require(
            all(
                re.fullmatch("[A-Za-z0-9_.+-]+", part) and part not in {".", ".."}
                for part in path.parts
            ),
            "native_sdk_path",
        )
        require(
            isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value),
            "native_sdk_hash",
        )
    require(
        {PurePosixPath(name).parts[0] for name in files} == PACKAGES | DIST_INFO,
        "native_sdk_top_inventory",
    )
    require(
        all(info + "/METADATA" in files for info in DIST_INFO),
        "native_sdk_metadata_required",
    )
    return manifest


def validate_sdk(stage, request):
    spec = sdk_request(request)
    if spec is None:
        return None
    manifest_path = stage / "build/native-sdk-manifest.json"
    root = stage / "build/native-sdk"
    for path in [stage / "build", manifest_path, root]:
        require(not path.is_symlink(), "native_sdk_symlink")
    require(manifest_path.is_file() and root.is_dir(), "native_sdk_missing")
    require(
        digest(manifest_path) == spec["manifest_sha256"], "native_sdk_manifest_mismatch"
    )
    manifest = validate_manifest(json.loads(manifest_path.read_text()))
    files = manifest["files"]
    observed = {}
    directories = set()
    for name in files:
        directories.update(
            p.as_posix() for p in PurePosixPath(name).parents if p.as_posix() != "."
        )
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        require(not path.is_symlink(), "native_sdk_symlink")
        if path.is_dir():
            require(name in directories, "native_sdk_unknown_directory")
        else:
            require(path.is_file(), "native_sdk_nonregular")
            observed[name] = digest(path)
    require(observed == files, "native_sdk_tree_mismatch")
    validate_sdk_versions(root, "native_sdk_versions")
    return manifest


def validate_sdk_versions(site, reason):
    installed = [
        (d.metadata["Name"], d.version)
        for d in importlib.metadata.distributions(path=[str(site)])
        if d.metadata["Name"] in PINS
    ]
    require(sorted(installed) == sorted(PINS.items()), reason)


def normalize_sdk_copy(stage, request):
    if validate_sdk(stage, request) is None:
        return
    root = stage / "build/native-sdk"
    paths = [root, *sorted(root.rglob("*"))]
    for path in paths:
        info = trusted_stat(path)
        require(info.st_uid == info.st_gid == 0, "native_sdk_copy_ownership")
    for path in paths:
        path.chmod(0o755 if path.is_dir() else 0o644)
    validate_sdk_copy_metadata(stage, request)


def validate_sdk_copy_metadata(stage, request):
    if validate_sdk(stage, request) is None:
        return
    root = stage / "build/native-sdk"
    for path in [root, *root.rglob("*")]:
        info = trusted_stat(path)
        require(
            info.st_uid == info.st_gid == 0
            and stat.S_IMODE(info.st_mode)
            == (0o755 if stat.S_ISDIR(info.st_mode) else 0o644),
            "native_sdk_copy_metadata",
        )


def dockerfile(base, request):
    extra = (
        "COPY --chown=0:0 native-sdk/ /usr/local/lib/python3.11/site-packages/\n"
        if sdk_request(request)
        else ""
    )
    return (
        "FROM "
        + base
        + "\n"
        + extra
        + "COPY --chown=10001:10001 backend/ /app/backend/app/\nCOPY --chown=10001:10001 static/ /app/backend/app/static/\n"
    )


def validate_dockerfile(content, base, request):
    require(content == dockerfile(base, request), "copy_only_dockerfile_required")


def validate_baseline_sdk(manifest, site=SITE):
    validate_manifest(manifest)
    for name in PACKAGES | DIST_INFO:
        require(
            not (site / name).exists() and not (site / name).is_symlink(),
            "baseline_sdk_collision",
        )
    for path in site.iterdir():
        stem = path.name.split(".")[0]
        require(stem not in PACKAGES, "baseline_sdk_collision")
        normalized = re.sub("[-_.]+", "-", path.name).lower()
        require(
            not any(
                normalized.startswith(re.sub("[-_.]+", "-", name).lower() + "-")
                for name in PINS
            ),
            "baseline_sdk_collision",
        )
    # Distribution names must also be absent, including alternate metadata spellings.
    names = {re.sub("[-_.]+", "-", name).lower() for name in PINS}
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        require(
            re.sub("[-_.]+", "-", distribution.metadata.get("Name", "")).lower()
            not in names,
            "baseline_sdk_collision",
        )


def verify_installed_sdk(manifest, site=SITE):
    validate_manifest(manifest)
    require(
        sys.version_info[:2] == (3, 11)
        and sys.platform == "linux"
        and platform.machine() == "x86_64",
        "installed_sdk_runtime",
    )
    for name, expected in manifest["files"].items():
        path = site / name
        require(
            not any(p.is_symlink() for p in [path, *path.parents]) and path.is_file(),
            "installed_sdk_path",
        )
        require(digest(path) == expected, "installed_sdk_hash")
    validate_sdk_versions(site, "installed_sdk_versions")
    sys.path.insert(0, str(site))
    sys.dont_write_bytecode = True
    for name in sorted(PACKAGES):
        module = importlib.import_module(name)
        require(
            Path(module.__file__).resolve().is_relative_to((site / name).resolve()),
            "installed_sdk_import_origin",
        )
    # crcmod supports its official Python implementation; Crypto must load its ABI.
    if site == SITE:
        crc = importlib.import_module("crcmod.predefined").mkPredefinedCrcFun("crc-64")
        require(crc(b"123456789") == 0x46A5A9388A5BEFFE, "installed_sdk_crc64")
        aes = importlib.import_module("Crypto.Cipher.AES")
        require(
            len(aes.new(b"0" * 16, aes.MODE_ECB).encrypt(b"0" * 16)) == 16,
            "installed_sdk_crypto",
        )


def check_container_sdk(run, container, manifest, *, baseline=False):
    code = (
        Path(__file__).read_text()
        + "\n"
        + ("validate_baseline_sdk" if baseline else "verify_installed_sdk")
        + "(json.load(sys.stdin))\n"
    )
    run(
        [
            "docker",
            "exec",
            "-i",
            "--user",
            "10001:10001",
            container,
            "python",
            "-B",
            "-c",
            code,
        ],
        data=json.dumps(manifest).encode(),
    )


def native_environment(config):
    require(isinstance(config, dict) and config == NATIVE_PATHS, "native_exact_paths")
    return {value: config[key] for key, value in NATIVE_FIELDS.items()}


def native_configuration(request, *, baseline=False):
    old = request.get("baseline_native")
    if "baseline_native" in request:
        native_environment(old)
    target = request.get("target_native", old)
    if "target_native" in request:
        native_environment(target)
    require(old is None or target == old, "existing_native_configuration_changed")
    return old if baseline else target


trusted_stat = lambda path: path.lstat()


def validate_native_storage(request):
    if native_configuration(request) is None:
        return {}
    root = Path(request["data_host"])
    directory = root / "native-production-tools"
    config = directory / "config.json"
    snapshot = directory / "snapshots.sqlite3"
    for path in [directory, config, snapshot, *directory.parents]:
        require(not path.is_symlink(), "native_storage_symlink")
    info = trusted_stat(directory)
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == info.st_gid == 10001
        and stat.S_IMODE(info.st_mode) == 0o700,
        "native_directory_metadata",
    )
    info = trusted_stat(config)
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == info.st_gid == 10001
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and info.st_size <= 128 * 1024,
        "native_config_metadata",
    )
    paths = [config, snapshot, root / "workbench.sqlite3"]
    workflow = request.get("target_workflow", request.get("baseline_workflow"))
    if workflow:
        paths.extend(
            root / Path(workflow[key]).name
            for key in ["database_path", "authority_database_path"]
        )
    identities = []
    for path in paths:
        require(not path.is_symlink(), "native_storage_symlink")
        if path.exists():
            info = trusted_stat(path)
            require(stat.S_ISREG(info.st_mode), "native_storage_nonregular")
            identities.append((info.st_dev, info.st_ino))
    require(len(identities) == len(set(identities)), "native_storage_inode_alias")
    if snapshot.exists():
        info = trusted_stat(snapshot)
        require(
            info.st_uid == info.st_gid == 10001
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1,
            "native_snapshot_metadata",
        )
    for suffix in ["-wal", "-shm", "-journal"]:
        sidecar = Path(str(snapshot) + suffix)
        require(not sidecar.is_symlink(), "native_storage_symlink")
        if sidecar.exists():
            info = trusted_stat(sidecar)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == info.st_gid == 10001
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 1,
                "native_sidecar_metadata",
            )
            identity = (info.st_dev, info.st_ino)
            require(identity not in identities, "native_storage_inode_alias")
            identities.append(identity)
    return {"native_config": digest(config)}
