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
    monkeypatch.setenv("TIERX_PYTHON_BROKER_TOKEN", "s" * 32)
    monkeypatch.setattr(broker, "docker", lambda *a, **kw: json.dumps({"SecurityOptions": ["seccomp"], "CgroupVersion": "2", "CgroupDriver": "systemd"}))
    with pytest.raises(broker.BrokerError, match="ROOTLESS_CGROUP"):
        broker.preflight()


def test_weak_broker_token_is_rejected(monkeypatch):
    monkeypatch.setenv("TIERX_PYTHON_BROKER_TOKEN", "")
    with pytest.raises(broker.BrokerError, match="STRONG_BROKER_TOKEN"):
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
    instance.test_pool.shutdown()
    restarted.test_pool.shutdown()


def test_draft_calls_have_a_separate_bounded_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "docker", lambda *a, **kw: "")
    instance = broker.Broker(str(tmp_path / "calls.sqlite"), "image", [])
    instance.pool.shutdown()
    instance.test_pool.shutdown()
    instance.pool, instance.test_pool = Mock(), Mock()
    request = {"execution_class": "TEST", "input": {}, "definition": {}}
    for index in range(10):
        instance.submit(str(index).zfill(64), request)
    with pytest.raises(broker.BrokerError, match="QUEUE_FULL"):
        instance.submit("a" * 64, request)
    instance.submit("b" * 64, {"input": {}, "definition": {}})
    assert instance.pool.submit.call_count == 1
    assert instance.test_pool.submit.call_count == 10


def test_cleanup_failure_is_retried_without_touching_other_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "docker", lambda *a, **kw: "")
    instance = broker.Broker(str(tmp_path / "calls.sqlite"), "image", [])
    remove = Mock(side_effect=[broker.BrokerError("failed"), None])
    monkeypatch.setattr(broker, "remove_network", remove)
    monkeypatch.setattr(broker, "remove_container", Mock())
    instance.cleanup("job", "proxy", "network")
    assert instance.unhealthy
    instance.retry_cleanup()
    assert not instance.unhealthy
    assert remove.call_args.args == ("network",)
    instance.pool.shutdown()
    instance.test_pool.shutdown()


def test_cancel_minimizes_transport_request_but_preserves_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "docker", lambda *a, **kw: "")
    instance = broker.Broker(str(tmp_path / "calls.sqlite"), "image", [])
    instance.pool.shutdown()
    instance.pool = Mock()
    request = {"input": {"evidence": "retained in tenant Mongo"}, "definition": {}}
    instance.submit("a" * 64, request)
    instance.cancel("a" * 64)
    with instance.db() as db:
        assert db.execute("SELECT request FROM calls").fetchone()[0] == ""
    instance.submit("a" * 64, request)
    assert instance.pool.submit.call_count == 1
    assert instance.get("a" * 64)["state"] == "CANCELLED"
    instance.test_pool.shutdown()
