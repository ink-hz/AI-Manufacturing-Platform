"""Private HTTP settings are strict, backward compatible, and non-secret."""
import json

import pytest

from manufacturing_platform.sap_connection import load_sap_connection_config


def settings():
    return {
        "version": 2, "transport": "soap_http", "environment": "test",
        "application_server": "sap.example.test", "system_number": "10",
        "system_id": "S4D", "client": "300", "username": "TEST-ACCOUNT",
        "password": "TEST-SECRET", "enabled": True, "read_only": True,
        "allowed_functions": ["RFC_PING"], "http_scheme": "https", "http_port": 44310,
        "allow_http_test": False, "timeout_seconds": 10,
        "max_response_bytes": 1024 * 1024, "ca_bundle_path": None,
    }


def load(tmp_path, value):
    path = tmp_path / "private.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return load_sap_connection_config(str(path))


def test_v2_https_settings_and_summary_are_non_secret(tmp_path):
    value = {**settings(), "ca_bundle_path": "/private/sap-ca.pem"}
    config = load(tmp_path, value)
    assert (config.http_scheme, config.http_port, config.timeout_seconds) == ("https", 44310, 10)
    assert config.ca_bundle_path == "/private/sap-ca.pem"
    summary = config.summary()
    assert summary["version"] == 2 and summary["protocol"] == "https"
    assert not summary["authentication_verified"]
    public = repr(config) + json.dumps(summary)
    for secret in [value["username"], value["password"], value["ca_bundle_path"]]:
        assert secret not in public


def test_v1_exact_shape_loads_with_safe_http_defaults(tmp_path):
    value = settings()
    for field in ["http_scheme", "http_port", "allow_http_test", "timeout_seconds", "max_response_bytes", "ca_bundle_path"]:
        value.pop(field)
    value.update(version=1, transport="rfc", allowed_functions=["Z_LEGACY_READ"])
    config = load(tmp_path, value)
    assert config.transport == "rfc" and config.http_scheme == "https"
    assert config.allow_http_test is False
    assert config.summary()["protocol"] == "rfc"


def test_http_requires_explicit_test_opt_in(tmp_path):
    value = {**settings(), "http_scheme": "http", "http_port": 8010, "allow_http_test": True}
    assert load(tmp_path, value).http_scheme == "http"
    with pytest.raises(ValueError, match="^invalid SAP connection configuration$"):
        load(tmp_path, {**value, "allow_http_test": False})


@pytest.mark.parametrize("change", [
    {"http_scheme": "ftp"}, {"http_scheme": "HTTPS"}, {"http_port": True},
    {"http_port": 0}, {"http_port": 65536}, {"http_port": "443"},
    {"allow_http_test": "true"}, {"timeout_seconds": 0}, {"timeout_seconds": 31},
    {"timeout_seconds": True}, {"timeout_seconds": 1.5}, {"max_response_bytes": 1023},
    {"max_response_bytes": 2097153}, {"max_response_bytes": True},
    {"ca_bundle_path": "relative.pem"}, {"ca_bundle_path": False},
    {"ca_bundle_path": "/private/\u0000.pem"}, {"verify_tls": False},
    {"environment": "production"}, {"transport": "rfc"},
    {"allowed_functions": ["Z_NOT_REVIEWED"]}, {"allowed_functions": ["*"]},
    {"enabled": True, "username": ""}, {"enabled": True, "allowed_functions": []},
])
def test_v2_rejects_unsafe_or_unknown_settings_without_secrets(tmp_path, change):
    with pytest.raises(ValueError, match="^invalid SAP connection configuration$") as error:
        load(tmp_path, {**settings(), **change})
    assert "TEST-SECRET" not in str(error.value)


@pytest.mark.parametrize("field", ["http_scheme", "http_port", "allow_http_test", "timeout_seconds", "max_response_bytes", "ca_bundle_path"])
def test_v2_requires_each_transport_field(tmp_path, field):
    value = settings()
    value.pop(field)
    with pytest.raises(ValueError, match="^invalid SAP connection configuration$"):
        load(tmp_path, value)


def test_v1_does_not_accept_v2_fields(tmp_path):
    with pytest.raises(ValueError):
        load(tmp_path, {**settings(), "version": 1, "transport": "rfc"})
