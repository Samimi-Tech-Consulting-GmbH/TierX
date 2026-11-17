"""Broker orchestration tests; these do not replace Linux isolation acceptance."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

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


def test_health_is_cached_and_never_waits_for_cleanup(monkeypatch):
    monkeypatch.setenv("TIERX_PYTHON_BROKER_TOKEN", "synthetic-health-token")
    instance = SimpleNamespace(unhealthy=True, image="image", retry_cleanup=Mock(side_effect=AssertionError("blocking cleanup")))
    handler = object.__new__(broker.Handler)
    handler.headers = {"Authorization": "Bearer synthetic-health-token"}
    handler.path, handler.command, handler.server = "/health", "GET", SimpleNamespace(broker=instance)
    assert handler.handle_request() == (503, {"state": "ISOLATION_UNAVAILABLE"})
    instance.unhealthy = False
    assert handler.handle_request()[0] == 200
    instance.retry_cleanup.assert_not_called()


def test_background_recovery_retries_on_30_second_schedule(monkeypatch):
    class StopLoop(BaseException): pass
    sleeper = Mock(side_effect=[None, StopLoop()])
    monkeypatch.setattr(broker.time, "sleep", sleeper)
    instance = SimpleNamespace(retry_cleanup=Mock())
    with pytest.raises(StopLoop): broker.Broker.recover_loop(instance)
    instance.retry_cleanup.assert_called_once_with()
    assert sleeper.call_args_list[0].args == (30,)


def test_startup_cleanup_uses_retry_helpers(tmp_path, monkeypatch):
    def docker(*args, **kwargs):
        return "orphan-job" if args[0] == "ps" else "orphan-net"
    monkeypatch.setattr(broker, "docker", docker)
    container, network = Mock(), Mock()
    monkeypatch.setattr(broker, "remove_container", container)
    monkeypatch.setattr(broker, "remove_network", network)
    instance = broker.Broker(str(tmp_path / "calls.sqlite"), "image", [])
    container.assert_called_once_with("orphan-job")
    network.assert_called_once_with("orphan-net")
    instance.pool.shutdown()
    instance.test_pool.shutdown()


@pytest.mark.parametrize("cancelled", [False, True])
def test_queued_execution_waits_for_recovery_and_honors_cancel(tmp_path, monkeypatch, cancelled):
    monkeypatch.setattr(broker, "docker", lambda *a, **kw: "")
    instance = broker.Broker(str(tmp_path / "calls.sqlite"), "image", [])
    instance.pool.shutdown()
    instance.pool = Mock()
    request = {"definition": {"source": "def run(alert,cluster): return {}", "timeout_seconds": 5,
        "destinations": [], "output_mode": "json", "output_schema": {"type": "object"}}, "input": {}}
    identity = "a" * 64
    instance.submit(identity, request)
    if cancelled: instance.cancel(identity)
    instance.unhealthy = True
    def recover():
        assert instance.get(identity)["state"] == ("CANCELLED" if cancelled else "PENDING")
        instance.unhealthy = False
    monkeypatch.setattr(instance, "retry_cleanup", recover)
    def docker(*args, **kwargs):
        if args[0] == "inspect": return json.dumps([{"NetworkSettings": {"Networks": {"tierx-py-" + identity[:48] + "-net": {"IPAddress": "192.0.2.10"}}}}])
        return "[]" if args[0] == "exec" else ""
    monkeypatch.setattr(broker, "docker", docker)
    execution = Mock(return_value={"result": {"observed": True}})
    monkeypatch.setattr(broker, "bounded_run", execution)
    instance.execute(identity, request)
    assert instance.get(identity)["state"] == ("CANCELLED" if cancelled else "SUCCEEDED")
    assert execution.call_count == (0 if cancelled else 1)
    instance.test_pool.shutdown()
