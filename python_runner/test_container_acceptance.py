"""Opt-in real-container checks. Full rootless broker/network acceptance is separate."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

IMAGE = os.getenv("TIERX_TEST_PYTHON_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="Set TIERX_TEST_PYTHON_IMAGE for real container checks")
spec = importlib.util.spec_from_file_location("acceptance_broker", Path(__file__).with_name("broker.py"))
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


def execute(source, timeout=10):
    name = "tierx-python-test-" + uuid4().hex
    command = ["docker", "run", "--rm", "-i", "--name", name, "--network=none", "--read-only",
        "--user=65532:65532", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory=256m",
        "--memory-swap=256m", "--cpus=1", "--pids-limit=64", "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
        IMAGE, "python", "-I", "/runner/execute.py"]
    try:
        return broker.bounded_run(command, json.dumps({"source": source, "input": {"alert": {}, "cluster": None}}).encode(), timeout, name)
    finally:
        broker.remove_container(name)
        found = subprocess.run(["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"], capture_output=True, check=True)
        assert not found.stdout.strip(), "Execution container leaked"


def test_container_has_no_host_mount_socket_route_or_root_write():
    value = execute("""import os, pathlib, socket, importlib.util
def run(alert, cluster):
    assert os.getuid() == 65532
    assert not pathlib.Path('/var/run/docker.sock').exists()
    assert not pathlib.Path('/run/python-docker.sock').exists()
    assert importlib.util.find_spec('pip') is None
    assert importlib.util.find_spec('ensurepip') is None
    try:
        pathlib.Path('/forbidden').write_text('no')
        raise AssertionError('root writable')
    except OSError:
        pass
    try:
        socket.create_connection(('169.254.169.254', 80), timeout=1)
        raise AssertionError('metadata reachable')
    except OSError:
        pass
    return {'isolated': True}
""")
    assert value == {"result": {"isolated": True}}


@pytest.mark.parametrize("source", ["def run(alert, cluster):\n while True: pass",
    "import os\ndef run(alert, cluster):\n os._exit(1)",
    "def run(alert, cluster):\n return bytearray(400 * 1024 * 1024)",
    "def run(alert, cluster):\n print('x' * 20000)\n return {}"])
def test_failures_are_bounded_and_containers_removed(source):
    with pytest.raises(broker.BrokerError):
        execute(source, timeout=3)


def test_process_limit_is_enforced_and_children_do_not_survive():
    result = execute("""import os, time
def run(alert, cluster):
    count = 0
    try:
        for _ in range(100):
            child = os.fork()
            if child == 0:
                time.sleep(20)
                os._exit(0)
            count += 1
    except OSError:
        return {'limited': count < 64}
    raise AssertionError('PID limit not enforced')
""")
    assert result == {"result": {"limited": True}}
