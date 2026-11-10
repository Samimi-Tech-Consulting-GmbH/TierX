"""Trusted private broker. Only this service sees the dedicated rootless socket."""
import concurrent.futures
from contextlib import contextmanager
import hmac
import ipaddress
import json
import os
import re
import selectors
import secrets
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tierx_workflows.python_tools import PythonToolError


class BrokerError(ValueError):
    pass


def docker(*args, timeout=15):
    result = subprocess.run(["docker", *args], capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise BrokerError("RUNNER_DOCKER_FAILURE")
    return result.stdout.decode()


def remove_container(name):
    """Docker --rm removal is asynchronous; do not race network cleanup."""
    deadline = time.monotonic() + 5
    while True:
        try:
            docker("rm", "-f", name, timeout=5)
        except BrokerError:
            pass
        if not docker("ps", "-aq", "--filter", "name=^/" + name + "$", timeout=5).strip():
            return
        if time.monotonic() >= deadline:
            raise BrokerError("PYTHON_CLEANUP_FAILED")
        time.sleep(0.1)


def preflight():
    if len(os.environ.get("TIERX_PYTHON_BROKER_TOKEN", "")) < 32:
        raise BrokerError("STRONG_BROKER_TOKEN_REQUIRED")
    info = json.loads(docker("info", "--format", "{{json .}}"))
    if not any("rootless" in item for item in info.get("SecurityOptions", [])) or info.get("CgroupVersion") != "2" or info.get("CgroupDriver") != "systemd":
        raise BrokerError("ROOTLESS_CGROUP_PREFLIGHT_FAILED")
    if not any("seccomp" in item and "unconfined" not in item for item in info.get("SecurityOptions", [])):
        raise BrokerError("SECCOMP_PREFLIGHT_FAILED")
    image = os.environ["TIERX_PYTHON_IMAGE"]
    if not re.fullmatch(r"(?:[a-zA-Z0-9./:_-]+@)?sha256:[0-9a-f]{64}", image):
        raise BrokerError("PINNED_PYTHON_IMAGE_REQUIRED")
    docker("image", "inspect", image)
    denied = json.loads(os.environ["TIERX_PYTHON_DENIED_NETWORKS"])
    if not denied or any(ipaddress.ip_network(value).prefixlen == 0 for value in denied):
        raise BrokerError("INFRASTRUCTURE_DENYLIST_REQUIRED")
    # Read effective delegated controllers, not merely Docker's advertised driver.
    controllers = Path(os.environ.get("TIERX_CGROUP_CONTROLLERS_FILE", "/runner-cgroup/cgroup.controllers")).read_text().split()
    if not {"cpu", "memory", "pids"} <= set(controllers):
        raise BrokerError("CGROUP_CONTROLLERS_NOT_DELEGATED")
    limits = json.loads(docker("run", "--rm", "--network=none", "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=64", image,
        "python", "-c", "import pathlib,json,sys; print(json.dumps({'python_version':list(sys.version_info[:2]),**{k:pathlib.Path('/sys/fs/cgroup/'+k).read_text().strip() for k in ['memory.max','pids.max','cpu.max']}}))"))
    if limits["python_version"] != [3, 12]:
        raise BrokerError("PYTHON_312_RUNTIME_REQUIRED")
    if limits["memory.max"] != "268435456" or limits["pids.max"] != "64" or limits["cpu.max"].split()[0] == "max":
        raise BrokerError("CGROUP_LIMITS_NOT_ENFORCED")
    return image, denied


def bounded_run(command, data, timeout, name, cancelled=lambda: False):
    if cancelled():
        raise BrokerError("PYTHON_CANCELLED")
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Writing stdin separately avoids deadlock when the child produces output first.
    writer = threading.Thread(target=lambda: _write(process, data), daemon=True)
    writer.start()
    streams = selectors.DefaultSelector()
    streams.register(process.stdout, selectors.EVENT_READ, "out")
    streams.register(process.stderr, selectors.EVENT_READ, "err")
    output, counts, deadline = bytearray(), {"out": 0, "err": 0}, time.monotonic() + timeout
    try:
        while streams.get_map():
            if cancelled():
                raise BrokerError("PYTHON_CANCELLED")
            if time.monotonic() >= deadline:
                raise BrokerError("PYTHON_TIMEOUT")
            for key, _ in streams.select(0.1):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    streams.unregister(key.fileobj)
                    continue
                counts[key.data] += len(chunk)
                if counts[key.data] > (70000 if key.data == "out" else 16384):
                    raise BrokerError("PYTHON_OUTPUT_LIMIT")
                if key.data == "out":
                    output.extend(chunk)
        if process.wait(timeout=2):
            raise BrokerError("PYTHON_EXECUTION_FAILED")
        return json.loads(output)
    finally:
        streams.close()
        if process.poll() is None:
            try:
                docker("kill", name, timeout=5)
            except Exception:
                pass
            finally:
                process.kill()
                process.wait()
        remove_container(name)


def _write(process, data):
    try:
        process.stdin.write(data)
        process.stdin.close()
    except (BrokenPipeError, OSError):
        pass


class Broker:
    def __init__(self, path, image, denied):
        self.path, self.image, self.denied = path, image, denied
        self.unhealthy = False
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.lock = threading.Lock()
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, checksum TEXT NOT NULL, request TEXT NOT NULL, state TEXT NOT NULL, result TEXT)")
            db.execute("UPDATE calls SET state='UNCERTAIN', result=? WHERE state IN ('PENDING','RUNNING')", (json.dumps({"error": "PYTHON_EXECUTION_UNCERTAIN"}),))
        # A broker restart never replays an uncertain side-effecting request.
        self.cleanup_orphans()

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def cleanup_orphans(self):
        for identity in docker("ps", "-aq", "--filter", "label=tierx.python.sandbox=true").split():
            docker("rm", "-f", identity)
        for identity in docker("network", "ls", "-q", "--filter", "label=tierx.python.sandbox=true").split():
            docker("network", "rm", identity)

    def submit(self, identity, request):
        from tierx_workflows.graph import checksum
        digest = checksum(request)
        if self.unhealthy:
            raise BrokerError("RUNNER_ISOLATION_UNAVAILABLE")
        with self.lock, self.db() as db:
            existing = db.execute("SELECT checksum FROM calls WHERE id=?", (identity,)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise BrokerError("PYTHON_REPLAY_CONFLICT")
                return
            if db.execute("SELECT count(*) FROM calls WHERE state IN ('PENDING','RUNNING')").fetchone()[0] >= 100:
                raise BrokerError("PYTHON_QUEUE_FULL")
            db.execute("INSERT INTO calls VALUES (?,?,?,'PENDING',?)", (identity, digest, json.dumps(request), json.dumps({"queued_at": time.time()})))
        self.pool.submit(self.execute, identity, request)

    def get(self, identity):
        with self.db() as db:
            row = db.execute("SELECT state,result FROM calls WHERE id=?", (identity,)).fetchone()
        return None if not row else {"state": row[0], **(json.loads(row[1]) if row[1] else {})}

    def execute(self, identity, request):
        from tierx_workflows.python_tools import output_envelope
        prefix = "tierx-py-" + identity[:48]
        network, proxy, name = prefix + "-net", prefix + "-proxy", prefix + "-job"
        started = time.time()
        metadata = {**(self.get(identity) or {}), "started_at": started, "deadline": started + request["definition"]["timeout_seconds"], "runtime_digest": self.image}
        metadata.pop("state", None)
        try:
            with self.db() as db:
                if db.execute("UPDATE calls SET state='RUNNING',result=? WHERE id=? AND state='PENDING'", (json.dumps(metadata), identity)).rowcount != 1:
                    return
            definition = request["definition"]
            if self.unhealthy:
                raise BrokerError("RUNNER_ISOLATION_UNAVAILABLE")
            docker("network", "create", "--internal", "--label", "tierx.python.sandbox=true", "-o", "com.docker.network.bridge.gateway_mode_ipv4=isolated", network)
            base = ["--label", "tierx.python.sandbox=true", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=64", "--user=65532:65532", "--tmpfs=/tmp:rw,noexec,nosuid,size=16m", "--log-driver=none"]
            # Proxy is trusted and contains no instance credentials. Each job gets its own proxy.
            denied = list(self.denied)
            # No sandbox may target the rootless host gateways or another sandbox.
            for network_id in docker("network", "ls", "-q").split():
                try:
                    records = json.loads(docker("network", "inspect", network_id))
                except BrokerError:
                    if docker("network", "ls", "-q", "--filter", "id=" + network_id).strip():
                        raise
                    continue  # Another job finished and removed its network.
                for net in records:
                    denied.extend(item["Subnet"] for item in (net.get("IPAM", {}).get("Config") or []) if item.get("Subnet"))
            proxy_token = secrets.token_urlsafe(32)
            docker("run", "-d", "--name", proxy, "--network", network, *base,
                "-e", "TIERX_JOB_AUDIT_FILE=/tmp/decisions.json",
                "-e", "TIERX_JOB_PROXY_TOKEN=" + proxy_token,
                "-e", "TIERX_JOB_DESTINATIONS=" + json.dumps(definition["destinations"]),
                "-e", "TIERX_JOB_DENIED_NETWORKS=" + json.dumps(denied), self.image, "python", "-I", "/runner/proxy.py")
            docker("network", "connect", "bridge", proxy)
            # Wait only for the local proxy listener; never retry a user's HTTP call.
            docker("exec", proxy, "python", "-c", "import socket,time\nfor attempt in range(30):\n try:\n  socket.create_connection(('127.0.0.1',8080),timeout=0.1).close(); break\n except OSError:\n  time.sleep(0.1)\nelse: raise RuntimeError('proxy unavailable')", timeout=5)
            address = json.loads(docker("inspect", proxy))[0]["NetworkSettings"]["Networks"][network]["IPAddress"]
            response = bounded_run(["docker", "run", "--rm", "-i", "--name", name, "--network", network, *base,
                "-e", f"TIERX_JOB_PROXY=http://{address}:8080/{proxy_token}", self.image, "python", "-I", "/runner/execute.py"],
                json.dumps({"source": definition["source"], "input": request["input"]}, ensure_ascii=False).encode(), max(0, metadata["deadline"] - time.time()), name,
                cancelled=lambda: self.get(identity)["state"] == "CANCELLED")
            result = {"result": output_envelope(response["result"], definition), "runtime_digest": self.image}
            state = "SUCCEEDED"
        except Exception as exc:
            safe = str(exc) if isinstance(exc, BrokerError) else "PYTHON_EXECUTION_FAILED"
            result, state = {"error": safe}, "FAILED"
        finally:
            try:
                decisions = json.loads(docker("exec", proxy, "python", "-c", "import pathlib; p=pathlib.Path('/tmp/decisions.json'); print(p.read_text() if p.exists() else '[]')"))
            except Exception:
                decisions = []
            metadata.update(duration_seconds=round(time.time() - started, 3), destination_decisions=decisions)
            for container in (name, proxy):
                try:
                    remove_container(container)
                except Exception:
                    self.unhealthy = True
            try:
                docker("network", "rm", network)
            except Exception:
                pass
        with self.db() as db:
            db.execute("UPDATE calls SET state=?,result=? WHERE id=? AND state='RUNNING'", (state, json.dumps({**metadata, **result}), identity))

    def cancel(self, identity):
        with self.db() as db:
            db.execute("UPDATE calls SET state='CANCELLED',result=? WHERE id=? AND state IN ('PENDING','RUNNING')", (json.dumps({"error": "PYTHON_CANCELLED"}), identity))
        for suffix in ("-job", "-proxy"):
            try:
                docker("rm", "-f", "tierx-py-" + identity[:48] + suffix)
            except Exception:
                pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def handle_request(self):
        from tierx_workflows.graph import canonical
        from tierx_workflows.python_tools import INPUT_SCHEMA, validate_definition
        from jsonschema import Draft202012Validator
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + os.environ["TIERX_PYTHON_BROKER_TOKEN"]).encode()):
            return 401, {"error": "UNAUTHORIZED"}
        if self.path == "/health" and self.command == "GET":
            if self.server.broker.unhealthy:
                return 503, {"state": "ISOLATION_UNAVAILABLE"}
            return 200, {"state": "READY", "runtime_digest": self.server.broker.image}
        if self.path == "/validate" and self.command == "POST":
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 150000:
                return 413, {"error": "REQUEST_LIMIT"}
            validate_definition(json.loads(self.rfile.read(size)))
            return 200, {"valid": True, "runtime_digest": self.server.broker.image}
        identity = self.path.removeprefix("/calls/")
        if len(identity) != 64 or any(char not in "0123456789abcdef" for char in identity):
            return 404, {"error": "NOT_FOUND"}
        if self.command == "POST":
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1200000:
                return 413, {"error": "REQUEST_LIMIT"}
            request = json.loads(self.rfile.read(size))
            request["definition"] = validate_definition(request["definition"])
            Draft202012Validator(INPUT_SCHEMA).validate(request["input"])
            if len(canonical(request["input"])) > 1048576:
                return 413, {"error": "PYTHON_INPUT_TOO_LARGE"}
            self.server.broker.submit(identity, request)
        elif self.command == "DELETE":
            self.server.broker.cancel(identity)
        result = self.server.broker.get(identity)
        return (200, result) if result else (404, {"error": "NOT_FOUND"})

    def respond(self):
        try:
            status, value = self.handle_request()
        except BrokerError as exc:
            code = str(exc)
            status = 409 if code == "PYTHON_REPLAY_CONFLICT" else 429 if code == "PYTHON_QUEUE_FULL" else 503
            value = {"error": code}
        except PythonToolError as exc:
            status, value = 422, {"error": str(exc)}
        except Exception:
            status, value = 422, {"error": "PYTHON_REQUEST_INVALID"}
        encoded = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    do_GET = do_POST = do_DELETE = respond


if __name__ == "__main__":
    os.umask(0o077)
    image, denied = preflight()
    server = ThreadingHTTPServer(("0.0.0.0", 8095), Handler)
    server.broker = Broker(os.environ.get("TIERX_PYTHON_STATE", "/data/calls.sqlite"), image, denied)
    server.serve_forever()
