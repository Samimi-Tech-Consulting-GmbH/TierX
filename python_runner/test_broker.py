"""Broker orchestration tests; these do not replace Linux isolation acceptance."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location("tierx_python_broker", Path(__file__).with_name("broker.py"))
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


def test_rootful_runtime_is_rejected(monkeypatch):
    monkeypatch.setattr(broker, "docker", lambda *a, **kw: json.dumps({"SecurityOptions": ["seccomp"], "CgroupVersion": "2", "CgroupDriver": "systemd"}))
    with pytest.raises(broker.BrokerError, match="ROOTLESS_CGROUP"):
        broker.preflight()


def test_durable_identity_conflicts_restart_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "docker", lambda *a, **kw: "")
    instance = broker.Broker(str(tmp_path / "calls.sqlite"), "image@sha256:abc", ["10.0.0.0/24"])
    instance.pool.shutdown()
    instance.pool = Mock()
    instance.submit("a" * 64, {"input": {}, "definition": {}})
    instance.submit("a" * 64, {"input": {}, "definition": {}})
    assert instance.pool.submit.call_count == 1
    with pytest.raises(broker.BrokerError, match="CONFLICT"):
        instance.submit("a" * 64, {"input": {"changed": True}})
    instance.cancel("a" * 64)
    assert instance.get("a" * 64)["state"] == "CANCELLED"
    instance.submit("b" * 64, {"input": {}, "definition": {}})
    restarted = broker.Broker(instance.path, instance.image, instance.denied)
    assert restarted.get("b" * 64)["state"] == "UNCERTAIN"
    restarted.pool.shutdown()
