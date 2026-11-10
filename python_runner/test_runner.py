import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from tierx_workflows.python_tools import validate_definition, input_snapshot, output_envelope, PythonToolError

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("tierx_python_proxy", ROOT / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


def definition(**changes):
    return {"code": "summarize", "name": "Summary", "description": "Synthetic summary", "tenant_ids": ["one"],
        "enabled": True, "source": "def run(alert, cluster):\n    return {'host': alert['normalized_payload'].get('host.name')}\n",
        "output_mode": "json", "output_schema": {"type": "object"}, "timeout_seconds": 30, "destinations": [], **changes}


def alert(**changes):
    return {"alert_id": "a", "tenant_id": "one", "alert_type": "synthetic", "source_system": "TEST",
        "raw_payload": {"must_not_leave": "raw"}, "normalized_payload": {"host.name": "EXAMPLE-HOST", "password": "not-public"}, **changes}


def test_input_is_tenant_scoped_normalized_and_bounded():
    snapshot = input_snapshot(alert())
    assert snapshot["cluster"] is None
    assert "raw_payload" not in str(snapshot)
    assert "not-public" not in str(snapshot)
    with pytest.raises(PythonToolError, match="TENANT"):
        input_snapshot(alert(), {"cluster_id": "c", "tenant_id": "other"})
    with pytest.raises(PythonToolError, match="MEMBER_LIMIT"):
        input_snapshot(alert(), members=[alert()] * 101)
    with pytest.raises(PythonToolError, match="TOO_LARGE"):
        input_snapshot(alert(normalized_payload={"value": "x" * 1048576}))


@pytest.mark.parametrize("source", ["async def run(alert, cluster): pass", "def run(alert): pass", "not python !"])
def test_invalid_entrypoints(source):
    with pytest.raises(PythonToolError):
        validate_definition(definition(source=source))


def test_output_modes_limits_and_json_schema():
    assert output_envelope("Evidence", definition(output_mode="text")) == {"type": "text", "text": "Evidence"}
    with pytest.raises(PythonToolError):
        output_envelope("x" * 16385, definition(output_mode="text"))
    assert output_envelope({"observed": True}, definition())["type"] == "json"
    with pytest.raises(PythonToolError):
        output_envelope({"value": float("nan")}, definition())


def test_nested_raw_documents_and_credentials_are_excluded():
    result = input_snapshot(alert(enrichment={"nested": {"raw_payload": {"value": "NEVER"}, "password": "NEVER", "safe": True}}))
    assert result["alert"]["enrichment"] == {"nested": {"safe": True}}


def test_cluster_is_optional_but_members_are_normalized():
    result = input_snapshot(alert(), {"cluster_id": "c", "tenant_id": "one", "internal": "NEVER"}, [alert()])
    assert result["cluster"]["members"][0]["alert_id"] == "a"
    assert "NEVER" not in str(result)


def test_stdlib_script_returns_json_without_print_leak():
    request = {"source": "import ipaddress\ndef run(alert, cluster):\n print('not returned')\n return {'in_network': str(ipaddress.ip_network('10.0.0.0/8'))}\n", "input": input_snapshot(alert())}
    result = subprocess.run([sys.executable, "-I", str(ROOT / "execute.py")], input=json.dumps(request), text=True, capture_output=True, timeout=5)
    assert result.returncode == 0
    assert json.loads(result.stdout)["result"] == {"in_network": "10.0.0.0/8"}
    assert "not returned" not in result.stdout + result.stderr


def test_proxy_pins_dns_rejects_mixed_answers_and_enforces_budget():
    policy = proxy.Policy([{"host": "allowed.example", "ports": [443]}], ["10.10.0.0/16"])
    with patch.object(proxy.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]):
        assert policy.resolve("allowed.example", 443) == "8.8.8.8"
        with pytest.raises(ValueError, match="NOT_APPROVED"):
            policy.resolve("allowed.example", 80)
    with patch.object(proxy.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]):
        with pytest.raises(ValueError, match="DENIED"):
            policy.resolve("allowed.example", 443)
    policy.attempts = 32
    with pytest.raises(ValueError, match="BUDGET"):
        policy.resolve("allowed.example", 443)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "169.254.169.254", "::ffff:127.0.0.1", "10.10.1.2",
    "100.64.0.1", "64:ff9b::a00:1", "2002:a00:1::1", "2001::1"])
def test_even_explicit_allow_cannot_override_protected_destinations(address):
    policy = proxy.Policy([{"host": address, "ports": [80]}], ["10.10.0.0/16"])
    with patch.object(proxy.socket, "getaddrinfo", return_value=[(2, 1, 6, "", (address, 80))]):
        with pytest.raises(ValueError, match="DENIED"):
            policy.resolve(address, 80)


def test_explicit_private_network_and_exact_port_allowed():
    policy = proxy.Policy([{"host": "10.20.0.0/16", "ports": [443]}], ["10.10.0.0/16"])
    with patch.object(proxy.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("10.20.1.2", 443))]):
        assert policy.resolve("10.20.1.2", 443) == "10.20.1.2"


def test_log_exhaustion_is_safe_error():
    request = {"source": "def run(alert, cluster):\n print('x' * 20000)\n return {}", "input": input_snapshot(alert())}
    result = subprocess.run([sys.executable, "-I", str(ROOT / "execute.py")], input=json.dumps(request), text=True, capture_output=True, timeout=5)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"error": "PYTHON_EXECUTION_FAILED"}
