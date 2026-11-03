"""Versioned shared definitions and bounded, acyclic dependency snapshots."""
from copy import deepcopy
import re

from tierx_workflows.graph import GraphError, canonical, checksum, validate_graph
from tierx_workflows.connectors import validate_schema

CODE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
KINDS = {"workflow", "playbook", "agent"}


def validate_definition(kind, configuration):
    if kind not in KINDS or not isinstance(configuration, dict):
        raise GraphError("Invalid definition kind or configuration")
    if kind != "agent":
        graph = validate_graph(configuration)
        if graph["format_version"] != "2.0":
            raise GraphError("Shared definitions require graph format 2.0")
        if any(node["type"] in {"playbook", "enrichment_action", "knowledge_base"} for node in graph["nodes"]):
            raise GraphError("Use shared playbook calls, REST/MCP tools, and explicit KB retrieval nodes")
        if kind == "workflow" and set(graph.get("input_capabilities", ["raw"])) != {"raw"}:
            raise GraphError("Workflow ingestion provides raw input only")
        return graph
    allowed = {"profile_code", "prompt", "output_schema", "tools", "max_rounds", "max_calls", "input_scope"}
    if set(configuration) - allowed or not str(configuration.get("prompt", "")).strip():
        raise GraphError("Agent requires a prompt and supported settings")
    cfg = deepcopy(configuration)
    cfg.setdefault("tools", [])
    cfg.setdefault("max_rounds", 5)
    cfg.setdefault("max_calls", 10)
    cfg.setdefault("output_schema", {"type": "object"})
    if any(str(tool).startswith("action:") for tool in cfg["tools"]):
        raise GraphError("Use approved REST/MCP connectors instead of legacy action references")
    validate_schema(cfg["output_schema"])
    # Validate agents with exactly the same bounded node contract as execution.
    validate_graph(agent_graph(cfg))
    return cfg


def agent_graph(config):
    return {
        "format_version": "2.0", "input_capabilities": ["normalization"],
        "nodes": [
            {"id": "entry", "type": "entry", "config": {}},
            {"id": "reason", "type": "llm_tools", "config": config},
            {"id": "done", "type": "complete", "config": {"output_path": "nodes.reason.output.result"}},
        ],
        "edges": [
            {"id": "start", "source": "entry", "target": "reason"},
            {"id": "finish", "source": "reason", "target": "done"},
        ],
    }


def references(kind, configuration):
    graph = agent_graph(configuration) if kind == "agent" else configuration
    result = []
    for node in graph["nodes"]:
        cfg, nid = node.get("config", {}), node["id"]
        if node["type"] in {"playbook_call", "agent"}:
            result.append((nid, "agent" if node["type"] == "agent" else "playbook", cfg["definition_code"], cfg.get("revision")))
        if node["type"] == "playbook_selector":
            for code in sorted({*cfg.get("candidates", []), *cfg.get("mappings", {}).values(), cfg["fallback"]}):
                result.append((f"{nid}:playbook:{code}", "playbook", code, None))
        for tool in cfg.get("tools", []):
            parts = tool.split(":")
            if len(parts) == 2 and parts[0] in {"agent", "playbook"}:
                result.append((f"{nid}:{tool}", parts[0], parts[1], None))
    return result


def compile_bundle(root, resolve, tenant_id, resolve_resources):
    """resolve returns immutable published rows; never resolves from model output."""
    bundle = {}

    def visit(row, ancestors=()):
        identity = f"{row['kind']}:{row['code']}@{row['revision']}"
        if identity in ancestors or any(item.split("@")[0] == identity.split("@")[0] for item in ancestors):
            raise GraphError("Recursive definition references are forbidden")
        if len(ancestors) > 3:
            raise GraphError("Maximum three nested definition calls")
        if tenant_id not in row["tenant_ids"] or not row.get("enabled", True):
            raise GraphError("Definition is not authorized for this tenant")
        if identity in bundle:
            return identity
        if len(bundle) >= 100:
            raise GraphError("Too many referenced definitions")
        config = validate_definition(row["kind"], row["configuration"])
        graph = agent_graph(config) if row["kind"] == "agent" else config
        item = {"kind": row["kind"], "code": row["code"], "revision": row["revision"],
                "name": row["name"], "description": row.get("description", ""),
                "graph": deepcopy(graph), "checksum": checksum(config),
                "resources": resolve_resources(graph), "references": {}}
        bundle[identity] = item
        for slot, kind, code, revision in references(row["kind"], config):
            item["references"][slot] = visit(resolve(kind, code, revision), (*ancestors, identity))
        return identity

    identity = visit(root)
    validate_parallel_effects(bundle)
    result = {"root": identity, "definitions": bundle}
    if len(canonical(result)) > 4 * 1024 * 1024:
        raise GraphError("Compiled definition bundle exceeds 4 MiB")
    return result


def validate_parallel_effects(bundle):
    """Resolve subflow effects before allowing parallel writes to the same alert."""
    effect_names = {"normalization": "normalization", "validation": "validation", "fingerprint": "fingerprint",
        "correlation": "correlation", "persist_analysis": "analysis", "playbook": "legacy_playbook",
        "knowledge_base": "knowledge", "kb_deterministic": "knowledge", "kb_semantic": "knowledge"}
    cache = {}
    def effects(identity):
        if identity not in cache:
            item = bundle[identity]
            cache[identity] = set().union(*(node_effects(item, node) for node in item["graph"]["nodes"]))
        return cache[identity]
    def node_effects(item, node):
        result = {effect_names[node["type"]]} if node["type"] in effect_names else set()
        for slot, reference in item["references"].items():
            if slot == node["id"] or slot.startswith(node["id"] + ":"):
                result |= effects(reference)
        return result
    for item in bundle.values():
        graph = item["graph"]
        by_id = {node["id"]: node for node in graph["nodes"]}
        edges = [edge for edge in graph["edges"] if edge.get("sourceHandle") != "tool"]
        for node in graph["nodes"]:
            if node["type"] != "fork":
                continue
            branches = []
            for edge in edges:
                if edge["source"] != node["id"]:
                    continue
                found, pending, writes = set(), [edge["target"]], set()
                while pending:
                    identity = pending.pop()
                    if identity in found or identity == node["config"]["join_id"]:
                        continue
                    found.add(identity)
                    writes |= node_effects(item, by_id[identity])
                    pending.extend(edge["target"] for edge in edges if edge["source"] == identity)
                if any(writes & existing for existing in branches):
                    raise GraphError("Conflicting parallel writes through nested definitions")
                branches.append(writes)
