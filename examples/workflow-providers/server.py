"""Synthetic context providers. No scanning, credentials checks, or external I/O."""

import hashlib
import hmac
import json
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = {
    "asset_context": "Look up synthetic asset ownership and criticality",
    "identity_context": "Look up synthetic account privileges",
    "indicator_reputation": "Look up synthetic indicator reputation",
    "maintenance_context": "Check a synthetic approved maintenance record",
    "related_observations": "Retrieve synthetic related security observations",
}
INPUT = {
    "type": "object",
    "properties": {"value": {"type": "string", "maxLength": 256}},
    "required": ["value"],
    "additionalProperties": False,
}
OUTPUT = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "subject": {"type": "string"},
        "outcome": {"type": "string"},
        "context": {"type": "string"},
    },
    "required": ["source", "subject", "outcome", "context"],
    "additionalProperties": False,
}


def observe(tool, arguments):
    if (
        tool not in TOOLS
        or set(arguments) != {"value"}
        or not isinstance(arguments["value"], str)
        or len(arguments["value"]) > 256
    ):
        raise ValueError("Invalid tool arguments")
    subject = arguments["value"]
    known = {
        ("asset_context", "DB01"): (
            "CRITICAL_ASSET",
            "DB01 is a synthetic production database owned by the database team.",
        ),
        ("identity_context", "svc_backup"): (
            "SERVICE_ACCOUNT",
            "svc_backup is a privileged backup service account; interactive use is unexpected.",
        ),
        ("indicator_reputation", "203.0.113.44"): (
            "SUSPICIOUS",
            "The documentation-only address is marked suspicious in this synthetic fixture.",
        ),
        ("maintenance_context", "CHG-TEST-001"): (
            "APPROVED",
            "Approved synthetic maintenance permits a backup script on DB01; it does not authorize unrelated activity.",
        ),
        ("related_observations", "DB01"): (
            "OBSERVED",
            "Synthetic observations: an interactive service-account session followed by PowerShell execution.",
        ),
    }
    outcome, context = known.get(
        (tool, subject),
        (
            "UNKNOWN",
            "No synthetic record exists. Missing information is not evidence of benign activity.",
        ),
    )
    return {
        "source": "synthetic-example",
        "subject": subject,
        "outcome": outcome,
        "context": context,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log authorization headers or payloads.

    def send(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send(
            200 if self.path == "/health" else 405 if self.path == "/mcp" else 404,
            {"synthetic": True},
        )

    def do_POST(self):
        if self.headers.get("Origin"):
            return self.send(403, {"error": "browser_origin_not_allowed"})
        token = os.environ.get("EXAMPLE_PROVIDER_TOKEN", "")
        if not token or not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + token
        ):
            return self.send(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                return self.send(413, {"error": "size"})
            body = json.loads(self.rfile.read(length))
            if self.path == "/v1/chat/completions":
                return self.send(200, synthetic_model(body))
            if self.path == "/fail":
                return self.send(503, {"error": "synthetic_unavailable"})
            if self.path == "/malformed":
                return self.send(200, {"unexpected": True})
            if self.path == "/slow":
                time.sleep(
                    min(30, max(0, float(os.getenv("EXAMPLE_DELAY_SECONDS", "2"))))
                )
            if self.path == "/mcp":
                return self.mcp(body)
            if self.path not in {"/rest", "/slow"}:
                return self.send(404, {"error": "path"})
            identity = body["delivery_id"]
            digest = hashlib.sha256(
                json.dumps([body["tool"], body["arguments"]], sort_keys=True).encode()
            ).hexdigest()
            with sqlite3.connect(
                os.getenv("EXAMPLE_DB", "/data/deliveries.sqlite")
            ) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, digest TEXT, output TEXT)"
                )
                row = db.execute(
                    "SELECT digest, output FROM deliveries WHERE id=?", (identity,)
                ).fetchone()
                if row and row[0] != digest:
                    return self.send(409, {"error": "delivery_conflict"})
                result = (
                    json.loads(row[1])
                    if row
                    else observe(body["tool"], body["arguments"])
                )
                db.execute(
                    "INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?)",
                    (identity, digest, json.dumps(result)),
                )
            return self.send(200, result)
        except (ValueError, KeyError, TypeError):
            return self.send(422, {"error": "invalid_request"})

    def mcp(self, body):
        method = body.get("method")
        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "TierX synthetic context", "version": "1.0.0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": description,
                        "inputSchema": INPUT,
                        "outputSchema": OUTPUT,
                        "annotations": {"readOnlyHint": True, "idempotentHint": True},
                    }
                    for name, description in TOOLS.items()
                ]
            }
        elif method == "tools/call":
            params = body["params"]
            identity = params.get("_meta", {}).get("tierx/delivery_id")
            if identity:
                digest = hashlib.sha256(
                    json.dumps(
                        [params["name"], params["arguments"]], sort_keys=True
                    ).encode()
                ).hexdigest()
                with sqlite3.connect(
                    os.getenv("EXAMPLE_DB", "/data/deliveries.sqlite")
                ) as db:
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, digest TEXT, output TEXT)"
                    )
                    row = db.execute(
                        "SELECT digest, output FROM deliveries WHERE id=?", (identity,)
                    ).fetchone()
                    if row and row[0] != digest:
                        return self.send(409, {"error": "delivery_conflict"})
                    output = (
                        json.loads(row[1])
                        if row
                        else observe(params["name"], params["arguments"])
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?)",
                        (identity, digest, json.dumps(output)),
                    )
            else:
                output = observe(params["name"], params["arguments"])
            result = {
                "content": [{"type": "text", "text": json.dumps(output)}],
                "structuredContent": output,
                "isError": False,
            }
        else:
            return self.send(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"code": -32601, "message": "Unsupported method"},
                },
            )
        self.send(200, {"jsonrpc": "2.0", "id": body.get("id"), "result": result})


def synthetic_model(body):
    """Protocol fixture, explicitly not an inference model or a verdict engine."""
    messages = body.get("messages", [])
    tools = body.get("tools", [])
    if tools and not any(message.get("role") == "tool" for message in messages):
        subjects = ["DB01", "svc_backup", "203.0.113.44", "CHG-TEST-001"]
        calls = [
            {
                "id": f"synthetic-call-{i}",
                "type": "function",
                "function": {
                    "name": tool["function"]["name"],
                    "arguments": json.dumps(
                        {
                            "value": "test"
                            if tool["function"]["name"] == "echo"
                            else subjects[i % len(subjects)]
                        }
                    ),
                },
            }
            for i, tool in enumerate(tools)
        ]
        message = {"role": "assistant", "content": None, "tool_calls": calls}
    else:
        schema = body.get("response_format", {}).get("json_schema", {}).get("schema")
        if not schema:
            for item in messages:
                marker = "Return a JSON final result matching: "
                if (item.get("content") or "").startswith(marker):
                    schema = json.loads(item["content"][len(marker) :])

        def fill(spec):
            if "enum" in spec:
                return spec["enum"][0]
            kind = spec.get("type", "object")
            if kind == "object":
                return {
                    key: fill(value)
                    for key, value in spec.get("properties", {}).items()
                    if key in spec.get("required", [])
                }
            if kind == "array":
                return [fill(spec.get("items", {"type": "string"}))]
            return {
                "boolean": True,
                "number": 1,
                "integer": 1,
                "string": "Synthetic protocol fixture; inspect tool evidence.",
            }.get(kind)

        result = fill(schema or {"type": "object"})
        message = {"role": "assistant", "content": json.dumps(result)}
    return {
        "id": "synthetic-response",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            }
        ],
    }


if __name__ == "__main__":
    if not os.environ.get("EXAMPLE_PROVIDER_TOKEN"):
        raise SystemExit("Set EXAMPLE_PROVIDER_TOKEN before starting")
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
