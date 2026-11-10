"""One-invocation egress proxy. No general forwarding, credentials or redirects."""
import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class Policy:
    def __init__(self, targets, denied):
        self.targets = targets
        self.denied = [ipaddress.ip_network(item, strict=False) for item in denied]
        self.lock, self.attempts = threading.Lock(), 0
        self.decisions = []

    def resolve(self, host, port):
        try:
            address = self._resolve(host, port)
        except Exception:
            self.record(host, port, "DENIED")
            raise
        self.record(host, port, "APPROVED", address)
        return address

    def record(self, host, port, decision, address=None):
        with self.lock:
            if len(self.decisions) >= 32:
                return
            self.decisions.append({"host": str(host)[:253], "port": port if type(port) is int else None,
                                   "decision": decision, "address": address})
            if os.environ.get("TIERX_JOB_AUDIT_FILE"):
                Path(os.environ["TIERX_JOB_AUDIT_FILE"]).write_text(json.dumps(self.decisions))

    def _resolve(self, host, port):
        if not isinstance(host, str) or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("INVALID_DESTINATION")
        host = host.lower().rstrip(".")
        with self.lock:
            self.attempts += 1
            if self.attempts > 32:
                raise ValueError("NETWORK_BUDGET_EXHAUSTED")
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        if not addresses:
            raise ValueError("DNS_FAILURE")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.version == 6 and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved or any(ip in net for net in self.denied if net.version == ip.version):
                raise ValueError("DESTINATION_DENIED")
            allowed = False
            for target in self.targets:
                if port not in target["ports"]:
                    continue
                try:
                    network = ipaddress.ip_network(target["host"], strict=False)
                    allowed |= ip.version == network.version and ip in network
                except ValueError:
                    allowed |= host == target["host"]
            if not allowed:
                raise ValueError("DESTINATION_NOT_APPROVED")
        return addresses[0]


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, address, secure):
        super().__init__(host, port, timeout=10)
        self.address, self.secure = address, secure

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), timeout=10)
        if self.secure:
            self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


def operate(policy, operation, value):
    if operation == "/tcp":
        host, port = value["host"], value["port"]
        address = policy.resolve(host, port)
        try:
            with socket.create_connection((address, port), timeout=5):
                return {"reachable": True}
        except OSError:
            return {"reachable": False}
    if operation != "/http":
        raise ValueError("UNKNOWN_OPERATION")
    parts = urlsplit(value["url"])
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("INVALID_HTTP_URL")
    method = value.get("method", "GET")
    if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("INVALID_HTTP_METHOD")
    body = value.get("body")
    if body is not None and (not isinstance(body, str) or len(body.encode()) > 16384):
        raise ValueError("HTTP_BODY_LIMIT")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    address = policy.resolve(parts.hostname, port)
    connection = PinnedHTTP(parts.hostname, port, address, parts.scheme == "https")
    try:
        connection.request(method, (parts.path or "/") + ("?" + parts.query if parts.query else ""), body=body,
            headers={"Content-Type": "text/plain; charset=utf-8"} if body is not None else {})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ValueError("HTTP_REDIRECT_DENIED")
        data = response.read(16385)
        if len(data) > 16384:
            raise ValueError("HTTP_RESPONSE_LIMIT")
        return {"status": response.status, "body": data.decode("utf-8", errors="replace")}
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 32768:
                raise ValueError("REQUEST_LIMIT")
            result = operate(self.server.policy, self.path, json.loads(self.rfile.read(size)))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            # Never return exception values (URLs, response bodies, evidence).
            known = {"DESTINATION_DENIED", "DESTINATION_NOT_APPROVED", "NETWORK_BUDGET_EXHAUSTED", "HTTP_REDIRECT_DENIED", "HTTP_RESPONSE_LIMIT"}
            result = {"error": str(exc) if str(exc) in known else "NETWORK_OPERATION_FAILED"}
        encoded = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.policy = Policy(json.loads(os.environ["TIERX_JOB_DESTINATIONS"]), json.loads(os.environ["TIERX_JOB_DENIED_NETWORKS"]))
    server.serve_forever()
