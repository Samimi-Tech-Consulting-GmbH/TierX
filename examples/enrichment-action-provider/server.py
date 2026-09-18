#!/usr/bin/env python3
"""Deterministic signed enrichment-action example; performs no external action."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

def environment(name: str, default: str) -> str:
    return (
        os.environ.get(f"TIERX_{name}")
        or os.environ.get(name)
        or os.environ.get(f"SOC_MIND_{name}")
        or default
    )


SECRET = environment("EXAMPLE_ENRICHMENT_ACTION_SECRET", "")
ACTION_CODE = environment("EXAMPLE_ENRICHMENT_ACTION_CODE", "example-observer")
DATA_FILE = Path(environment("EXAMPLE_ENRICHMENT_ACTION_DATA", "/data/deliveries.json"))
MAX_BODY = 262_144
LOCK = threading.Lock()
ALLOWED_FIELDS = (
    "host.name",
    "host.hostname",
    "source.ip",
    "destination.ip",
    "destination.port",
    "user.name",
    "process.name",
    "file.path",
    "threat.technique.id",
)


def _load() -> dict[str, dict[str, Any]]:
    if not DATA_FILE.exists():
        return {}
    try:
        value = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save(value: dict[str, dict[str, Any]]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    temporary.replace(DATA_FILE)


def _resolve(value: dict[str, Any], path: str) -> Any:
    if path in value:
        return value[path]
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _response(body: dict[str, Any]) -> dict[str, Any]:
    delivery_id = str(body["delivery_id"])
    payload = body["alert"].get("normalized_payload") or {}
    observed = {
        field: value
        for field in ALLOWED_FIELDS
        if (value := _resolve(payload, field)) not in (None, "", [], {})
    }
    facts = ", ".join(
        f"{field}={json.dumps(value, ensure_ascii=False, sort_keys=True)}"
        for field, value in observed.items()
    )
    context = (
        "The deterministic reference provider observed these normalized fields: "
        + (facts or "none of the configured safe fields were present")
        + ". No scan, credential test, inference, or response action was performed."
    )
    return {
        "spec_version": "1.0",
        "delivery_id": delivery_id,
        "outcome": "OBSERVED",
        "context_text": context,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "TierXExampleAction/1.0"

    def _json(self, status: int, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "healthy", "action_code": ACTION_CODE})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/":
            self._json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not SECRET or length <= 0 or length > MAX_BODY:
            self._json(400, {"error": "invalid_request"})
            return
        raw = self.rfile.read(length)
        def compatible(suffix: str) -> str | None:
            canonical = self.headers.get(f"X-TierX-{suffix}", "").strip()
            legacy = self.headers.get(f"X-SOC-Mind-{suffix}", "").strip()
            if canonical and legacy and canonical != legacy:
                self._json(400, {"error": "conflicting_compatibility_headers"})
                return None
            return canonical or legacy

        delivery_id = compatible("Delivery-ID")
        timestamp = compatible("Timestamp")
        signature = compatible("Signature")
        version = compatible("Action-Version")
        if None in (delivery_id, timestamp, signature, version):
            return
        if (
            version != "1"
            or not re.fullmatch(r"[0-9]{10,}", timestamp)
            or abs(int(time.time()) - int(timestamp)) > 300
        ):
            self._json(401, {"error": "invalid_signature_metadata"})
            return
        expected = hmac.new(
            SECRET.encode(),
            timestamp.encode() + b"." + delivery_id.encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, f"v1={expected}"):
            self._json(401, {"error": "invalid_signature"})
            return
        try:
            body = json.loads(raw)
            if (
                body.get("spec_version") != "1.0"
                or body.get("delivery_id") != delivery_id
                or body.get("action", {}).get("code") != ACTION_CODE
                or not isinstance(body.get("alert", {}).get("normalized_payload"), dict)
            ):
                raise ValueError
        except Exception:
            self._json(422, {"error": "invalid_contract"})
            return
        with LOCK:
            deliveries = _load()
            response = deliveries.get(delivery_id)
            if response is None:
                response = _response(body)
                deliveries[delivery_id] = response
                _save(deliveries)
        self._json(200, response)

    def log_message(self, format: str, *args: Any) -> None:
        # Do not log request bodies or signing headers.
        print(f"{self.address_string()} {format % args}")


if __name__ == "__main__":
    if not SECRET:
        raise SystemExit("EXAMPLE_ENRICHMENT_ACTION_SECRET is required")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
