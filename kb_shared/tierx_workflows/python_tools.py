"""Version-one Python tool contracts. This module never executes user code."""
import ast
import ipaddress
import json
import re
from typing import TypedDict

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from tierx_workflows.graph import canonical
from tierx_workflows.safety import sanitize, sensitive
from tierx_workflows.connectors import validate_schema

CONTRACT_VERSION = "1.0"
MAX_INPUT = 1024 * 1024
MAX_CODE = 65536
CODE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class AlertContext(TypedDict):
    alert_id: str
    tenant_id: str
    alert_type: str
    source_system: str
    event_time: str | None
    normalized_payload: dict
    enrichment: dict
    correlation: dict


class ClusterContext(TypedDict):
    cluster_id: str
    tenant_id: str
    metadata: dict
    correlation_basis: dict
    members: list[AlertContext]


ALERT_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": list(AlertContext.__annotations__), "properties": {
        **{key: {"type": "string"} for key in ("alert_id", "tenant_id", "alert_type", "source_system")},
        "event_time": {"type": ["string", "null"]},
        **{key: {"type": "object"} for key in ("normalized_payload", "enrichment", "correlation")}}}
CLUSTER_SCHEMA = {"type": ["object", "null"], "additionalProperties": False,
    "required": list(ClusterContext.__annotations__), "properties": {
        "cluster_id": {"type": "string"}, "tenant_id": {"type": "string"},
        "metadata": {"type": "object"}, "correlation_basis": {"type": "object"},
        "members": {"type": "array", "maxItems": 100, "items": ALERT_SCHEMA}}}
INPUT_SCHEMA = {"type": "object", "additionalProperties": False,
    "$id": "urn:tierx:python-tools:input:1.0", "$schema": "https://json-schema.org/draft/2020-12/schema",
    "required": ["contract_version", "alert", "cluster"], "properties": {
        "contract_version": {"const": CONTRACT_VERSION}, "alert": ALERT_SCHEMA, "cluster": CLUSTER_SCHEMA}}


class PythonToolError(ValueError):
    pass


def safe_context(value):
    """Drop non-contract data recursively, including embedded source documents."""
    if isinstance(value, dict):
        return {str(key): safe_context(item) for key, item in value.items()
                if not sensitive(key) and str(key).lower() not in {
                    "_id", "raw_payload", "raw_alert", "deployment", "deployment_config",
                    "environment", "env", "database", "internal", "resources"}}
    if isinstance(value, list):
        return [safe_context(item) for item in value]
    return sanitize(value)


def validate_definition(value, *, syntax=True):
    allowed = {"code", "name", "description", "source", "tenant_ids", "enabled", "output_mode",
               "output_schema", "timeout_seconds", "destinations"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise PythonToolError("INVALID_PYTHON_TOOL")
    if not CODE.fullmatch(value.get("code", "")):
        raise PythonToolError("INVALID_PYTHON_TOOL_CODE")
    source = value.get("source", "")
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > MAX_CODE:
        raise PythonToolError("INVALID_PYTHON_SOURCE_SIZE")
    if syntax:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise PythonToolError("PYTHON_SYNTAX_ERROR") from exc
        functions = [item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "run"]
        if len(functions) != 1 or isinstance(functions[0], ast.AsyncFunctionDef):
            raise PythonToolError("SYNCHRONOUS_RUN_REQUIRED")
        args = functions[0].args
        if [arg.arg for arg in args.args] != ["alert", "cluster"] or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg:
            raise PythonToolError("RUN_REQUIRES_ALERT_AND_CLUSTER")
    if value.get("output_mode") not in {"text", "json"}:
        raise PythonToolError("INVALID_OUTPUT_MODE")
    validate_schema(value.get("output_schema", {"type": "object"}))
    if type(value.get("timeout_seconds", 30)) is not int or not 1 <= value.get("timeout_seconds", 30) <= 1800:
        raise PythonToolError("INVALID_PYTHON_TIMEOUT")
    destinations = value.get("destinations", [])
    if not isinstance(destinations, list) or len(destinations) > 32:
        raise PythonToolError("INVALID_DESTINATIONS")
    for target in destinations:
        if not isinstance(target, dict) or set(target) != {"host", "ports"}:
            raise PythonToolError("INVALID_DESTINATION")
        host, ports = target["host"], target["ports"]
        if not isinstance(host, str) or host != host.lower() or len(host) > 253:
            raise PythonToolError("INVALID_DESTINATION_HOST")
        try:
            ipaddress.ip_network(host, strict=False)
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", host):
                raise PythonToolError("INVALID_DESTINATION_HOST")
        if not isinstance(ports, list) or not 1 <= len(ports) <= 32 or any(type(p) is not int or not 1 <= p <= 65535 for p in ports):
            raise PythonToolError("INVALID_DESTINATION_PORTS")
    return {**value, "timeout_seconds": value.get("timeout_seconds", 30), "destinations": destinations,
            "output_schema": value.get("output_schema", {"type": "object"})}


def alert_context(alert):
    result = {key: str(alert.get(key, "")) for key in ("alert_id", "tenant_id", "alert_type", "source_system")}
    timestamp = alert.get("timestamp") or alert.get("created_at")
    result.update(event_time=timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp) if timestamp else None,
        normalized_payload=safe_context(alert.get("normalized_payload") or {}),
        enrichment=safe_context(alert.get("enrichment") or {}), correlation=safe_context(alert.get("correlation_result") or {}))
    return result


def input_snapshot(alert, cluster=None, members=()):
    if len(members) > 100:
        raise PythonToolError("PYTHON_CLUSTER_MEMBER_LIMIT")
    tenant = alert["tenant_id"]
    if cluster and (cluster.get("tenant_id") != tenant or any(member.get("tenant_id") != tenant for member in members)):
        raise PythonToolError("PYTHON_TENANT_MISMATCH")
    cluster_value = None if not cluster else {"cluster_id": cluster["cluster_id"], "tenant_id": tenant,
        "metadata": sanitize({key: cluster[key] for key in ("alert_count", "severity", "clustering_status", "status") if key in cluster}),
        "correlation_basis": safe_context(cluster.get("correlation_basis") or {}),
        "members": [alert_context(member) for member in sorted(members, key=lambda item: item["alert_id"])]}
    result = {"contract_version": CONTRACT_VERSION, "alert": alert_context(alert), "cluster": cluster_value}
    try:
        encoded = canonical(result)
        result = json.loads(encoded)
        Draft202012Validator(INPUT_SCHEMA).validate(result)
    except (ValidationError, ValueError, TypeError) as exc:
        raise PythonToolError("PYTHON_INPUT_INVALID") from exc
    if len(encoded) > MAX_INPUT:
        raise PythonToolError("PYTHON_INPUT_TOO_LARGE")
    return result


def output_envelope(value, definition):
    mode = definition["output_mode"]
    if mode == "text":
        if not isinstance(value, str) or len(value.encode()) > 16384:
            raise PythonToolError("PYTHON_TEXT_OUTPUT_INVALID")
        result = {"type": "text", "text": value}
    else:
        try:
            size = len(json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode())
        except (ValueError, TypeError) as exc:
            raise PythonToolError("PYTHON_JSON_OUTPUT_INVALID") from exc
        if not isinstance(value, dict) or size > 65536:
            raise PythonToolError("PYTHON_JSON_OUTPUT_INVALID")
        try:
            Draft202012Validator(definition["output_schema"]).validate(value)
        except ValidationError as exc:
            raise PythonToolError("PYTHON_OUTPUT_SCHEMA_INVALID") from exc
        result = {"type": "json", "data": value}
    return result
