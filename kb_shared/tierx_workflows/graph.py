import hashlib
import ipaddress
import json
import math
import re
from collections import defaultdict, deque

NODE_TYPES = {
    "entry",
    "validation",
    "normalization",
    "fingerprint",
    "playbook",
    "knowledge_base",
    "enrichment_action",
    "correlation",
    "llm_analysis",
    "llm_tools",
    "decision",
    "fork",
    "join",
    "catch",
    "complete",
    "dead_letter",
}
MUTATIONS = {
    "normalization",
    "fingerprint",
    "correlation",
    "llm_analysis",
    "playbook",
    "knowledge_base",
}
OPERATORS = {
    "eq",
    "ne",
    "exists",
    "in",
    "contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "cidr_contains",
}
PORTS = {
    "decision": {"true", "false", "error"},
    "fork": None,
    "complete": set(),
    "dead_letter": set(),
}
CONFIG = {
    "entry": set(),
    "validation": {"schema_id", "schema_version", "critical_fields", "field_mapping"},
    "normalization": {"schema_id", "schema_version", "field_mapping"},
    "fingerprint": {"fields", "window_hours"},
    "playbook": {"playbook_id", "version"},
    "knowledge_base": {"top_k", "retrieval_mode"},
    "enrichment_action": {"action_code"},
    "correlation": {"lookback_hours", "debounce_ms", "grouping_hours"},
    "llm_analysis": {"profile_code", "prompt", "output_schema"},
    "llm_tools": {
        "profile_code",
        "prompt",
        "output_schema",
        "tools",
        "max_rounds",
        "max_calls",
    },
    "decision": {"path", "operator", "value"},
    "fork": {"branches", "join_id"},
    "join": {"fork_id"},
    "catch": {"replacement", "output_schema"},
    "complete": set(),
    "dead_letter": set(),
}


class GraphError(ValueError):
    pass


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def checksum(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def value_at(value, path):
    if not isinstance(path, str) or len(path) > 512:
        raise GraphError("Invalid field path")
    parts = path.split(".")
    for index, key in enumerate(parts):
        if not isinstance(value, dict):
            return None
        remaining = ".".join(parts[index:])
        if remaining in value:
            return value[remaining]
        value = value.get(key)
    return value


def decide(context, config):
    actual = value_at(context, config["path"])
    expected = config.get("value")
    op = config["operator"]
    if op == "exists":
        return actual is not None
    if op == "eq":
        return type(actual) is type(expected) and actual == expected
    if op == "ne":
        return not (type(actual) is type(expected) and actual == expected)
    if op == "in":
        return isinstance(expected, list) and any(
            type(actual) is type(v) and actual == v for v in expected
        )
    if op == "contains":
        if isinstance(actual, list):
            return any(
                type(item) is type(expected) and item == expected for item in actual
            )
        return (
            isinstance(actual, str) and isinstance(expected, str) and expected in actual
        )
    if op == "cidr_contains":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        try:
            return ipaddress.ip_address(actual) in ipaddress.ip_network(
                expected, strict=False
            )
        except (ValueError, TypeError):
            return False
    if op in {"gt", "gte", "lt", "lte"}:
        if type(actual) not in (int, float) or type(expected) not in (int, float):
            return False
        return {
            "gt": actual > expected,
            "gte": actual >= expected,
            "lt": actual < expected,
            "lte": actual <= expected,
        }[op]
    raise GraphError("Unsupported decision operator")


def validate_graph(graph):
    if not isinstance(graph, dict) or set(graph) - {
        "format_version",
        "nodes",
        "edges",
        "viewport",
    }:
        raise GraphError("Unknown graph fields")
    if graph.get("format_version") != "1.0":
        raise GraphError("Unsupported graph format")

    def coordinates(value, viewport=False):
        keys = {"x", "y", "zoom"} if viewport else {"x", "y"}
        if (
            not isinstance(value, dict)
            or set(value) != keys
            or any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in value.values()
            )
        ):
            raise GraphError("Invalid canvas coordinates")
        if viewport and not 0.1 <= value["zoom"] <= 4:
            raise GraphError("Invalid viewport zoom")

    if "viewport" in graph:
        coordinates(graph["viewport"], True)
    if len(canonical(graph)) > 1024 * 1024:
        raise GraphError("Graph exceeds 1 MiB")
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 100:
        raise GraphError("Expected 2–100 nodes")
    if not isinstance(edges, list) or len(edges) > 300:
        raise GraphError("Expected at most 300 edges")
    by_id, adjacency, incoming = {}, defaultdict(list), defaultdict(list)
    for node in nodes:
        if not isinstance(node, dict) or set(node) - {
            "id",
            "type",
            "config",
            "position",
            "label",
        }:
            raise GraphError("Unknown node fields")
        nid, kind = node.get("id"), node.get("type")
        if "position" in node:
            coordinates(node["position"])
        if "label" in node and (
            not isinstance(node["label"], str) or len(node["label"]) > 128
        ):
            raise GraphError("Invalid node label")
        if (
            not isinstance(nid, str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", nid)
            or nid in by_id
        ):
            raise GraphError("Invalid/duplicate node ID")
        if kind not in NODE_TYPES:
            raise GraphError("Unknown node type")
        cfg = node.get("config", {})
        if not isinstance(cfg, dict) or set(cfg) - CONFIG[kind]:
            raise GraphError(f"Invalid configuration for {nid}")
        for resource in ("profile_code", "action_code", "playbook_id", "schema_id"):
            if resource in cfg and (
                not isinstance(cfg[resource], str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", cfg[resource])
            ):
                raise GraphError("Invalid resource reference")
        for version in ("version", "schema_version"):
            if version in cfg and (
                not isinstance(cfg[version], (str, int))
                or isinstance(cfg[version], bool)
            ):
                raise GraphError("Invalid resource version")
        if kind == "catch" and not isinstance(cfg.get("replacement", {}), dict):
            raise GraphError("Catch replacement must be an object")
        if kind == "decision" and (
            cfg.get("operator") not in OPERATORS or not isinstance(cfg.get("path"), str)
        ):
            raise GraphError("Invalid decision")
        if kind in {"llm_analysis", "llm_tools"} and not cfg.get("profile_code"):
            raise GraphError("LLM profile required")
        if kind == "enrichment_action" and not cfg.get("action_code"):
            raise GraphError("Action reference required")
        if kind == "llm_tools":
            if not isinstance(cfg.get("tools", []), list):
                raise GraphError("Invalid tool allowlist")
            for tool in cfg.get("tools", []):
                if not isinstance(tool, str) or (
                    tool not in {"knowledge_base", "alert_evidence", "cluster_evidence"}
                    and not re.fullmatch(r"action:[a-z0-9][a-z0-9_-]{0,63}", tool)
                ):
                    raise GraphError("Unknown tool reference")
            if (
                type(cfg.get("max_rounds", 5)) is not int
                or not 1 <= cfg.get("max_rounds", 5) <= 5
            ):
                raise GraphError("Maximum five model rounds")
            if (
                type(cfg.get("max_calls", 10)) is not int
                or not 1 <= cfg.get("max_calls", 10) <= 10
            ):
                raise GraphError("Maximum ten tool calls")
            if (
                not isinstance(cfg.get("tools", []), list)
                or len(cfg.get("tools", [])) > 10
            ):
                raise GraphError("Invalid tool allowlist")
        if kind == "knowledge_base" and (
            type(cfg.get("top_k", 5)) is not int
            or not 1 <= cfg.get("top_k", 5) <= 20
            or cfg.get("retrieval_mode", "deterministic")
            not in {"deterministic", "hybrid"}
        ):
            raise GraphError("Invalid KB configuration")
        for name in ("field_mapping",):
            if name in cfg and (
                not isinstance(cfg[name], dict)
                or len(cfg[name]) > 128
                or any(
                    not isinstance(k, str) or not isinstance(v, str) or len(v) > 512
                    for k, v in cfg[name].items()
                )
            ):
                raise GraphError("Invalid field mapping")
        for name in ("critical_fields", "fields", "branches", "tools"):
            if name in cfg and (
                not isinstance(cfg[name], list)
                or len(cfg[name]) > 128
                or any(
                    not isinstance(v, str) or not v or len(v) > 512 for v in cfg[name]
                )
            ):
                raise GraphError("Invalid field list")
        if kind == "fork" and any(
            not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", branch)
            for branch in cfg.get("branches", [])
        ):
            raise GraphError("Invalid branch name")
        for name, maximum in (
            ("window_hours", 168),
            ("lookback_hours", 24),
            ("grouping_hours", 24),
        ):
            if name in cfg and (
                type(cfg[name]) is not int or not 1 <= cfg[name] <= maximum
            ):
                raise GraphError("Invalid time window")
        if "debounce_ms" in cfg and (
            not isinstance(cfg["debounce_ms"], dict)
            or set(cfg["debounce_ms"]) - {"critical", "high", "medium", "low"}
            or any(
                type(v) is not int or not 0 <= v <= 3600000
                for v in cfg["debounce_ms"].values()
            )
        ):
            raise GraphError("Invalid debounce configuration")
        if "output_schema" in cfg:
            from jsonschema import Draft202012Validator

            try:
                Draft202012Validator.check_schema(cfg["output_schema"])
            except Exception as exc:
                raise GraphError("Invalid output schema") from exc

            def check_refs(value):
                if isinstance(value, dict):
                    if set(value) & {
                        "$ref",
                        "$dynamicRef",
                        "pattern",
                        "patternProperties",
                    }:
                        raise GraphError(
                            "Schema references and regular expressions are not supported"
                        )
                    for name in ("properties", "$defs", "dependentSchemas"):
                        for child in value.get(name, {}).values():
                            check_refs(child)
                    for name in (
                        "items",
                        "additionalProperties",
                        "not",
                        "if",
                        "then",
                        "else",
                        "contains",
                    ):
                        check_refs(value.get(name))
                    for name in ("allOf", "anyOf", "oneOf", "prefixItems"):
                        for child in value.get(name, []):
                            check_refs(child)

            check_refs(cfg["output_schema"])
        by_id[nid] = node
    entries = [n["id"] for n in nodes if n["type"] == "entry"]
    if len(entries) != 1:
        raise GraphError("Exactly one entry required")
    connections = set()
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) - {
            "id",
            "source",
            "target",
            "sourceHandle",
        }:
            raise GraphError("Invalid edge fields")
        src, dst, port = (
            edge.get("source"),
            edge.get("target"),
            edge.get("sourceHandle", "success"),
        )
        if src not in by_id or dst not in by_id or dst == entries[0]:
            raise GraphError("Invalid edge endpoint")
        ports = PORTS.get(by_id[src]["type"], {"success", "error"})
        if ports is not None and port not in ports:
            raise GraphError("Invalid output port")
        if (src, port) in connections:
            raise GraphError("Use an explicit fork for parallel execution")
        connections.add((src, port))
        adjacency[src].append(dst)
        incoming[dst].append(src)
    degree = {nid: len(incoming[nid]) for nid in by_id}
    queue, order = deque(nid for nid, d in degree.items() if d == 0), []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for dst in adjacency[nid]:
            degree[dst] -= 1
            if not degree[dst]:
                queue.append(dst)
    if len(order) != len(nodes):
        raise GraphError("Cycles are not supported")
    reachable = set()

    def walk(nid):
        if nid in reachable:
            return
        reachable.add(nid)
        for dst in adjacency[nid]:
            walk(dst)

    walk(entries[0])
    if reachable != set(by_id):
        raise GraphError("Unreachable nodes")
    guaranteed = {}
    for nid in order:
        predecessors = incoming[nid]
        before = (
            set.intersection(*(guaranteed[p] for p in predecessors))
            if predecessors
            else set()
        )
        kind = by_id[nid]["type"]
        requirements = {
            "normalization": {"validation"},
            "fingerprint": {"normalization"},
            "playbook": {"normalization"},
            "knowledge_base": {"normalization"},
            "enrichment_action": {"normalization", "fingerprint"},
            "correlation": {"normalization", "fingerprint"},
            "llm_analysis": {"correlation"},
            "llm_tools": {"normalization"},
        }
        if not requirements.get(kind, set()) <= before:
            raise GraphError(f"Missing required upstream stage for {nid}")
        if (
            kind == "llm_tools"
            and any(
                name.startswith("action:")
                for name in by_id[nid].get("config", {}).get("tools", [])
            )
            and "fingerprint" not in before
        ):
            raise GraphError("Action tools require an upstream fingerprint")
        guaranteed[nid] = before | {kind}
    if sum(n["type"] == "correlation" for n in nodes) > 1:
        raise GraphError("Only one correlation node per graph")
    for node in nodes:
        nid, kind, cfg = node["id"], node["type"], node.get("config", {})
        if len(incoming[nid]) > 1 and kind not in {
            "join",
            "catch",
            "dead_letter",
            "complete",
        }:
            raise GraphError("Multiple inputs require join/catch/terminal")
        if kind in {"complete", "dead_letter"}:
            continue
        required = {"true", "false"} if kind == "decision" else {"success"}
        if kind == "fork":
            required = set(cfg.get("branches", []))
            join = by_id.get(cfg.get("join_id"), {})
            if (
                not 2 <= len(required) <= 5
                or len(required) != len(cfg.get("branches", []))
                or join.get("type") != "join"
                or join.get("config", {}).get("fork_id") != nid
            ):
                raise GraphError("Fork requires 2–5 unique branches and matching join")
            branch_sets = []
            for port in sorted(required):
                targets = [
                    e["target"]
                    for e in edges
                    if e["source"] == nid and e.get("sourceHandle", "success") == port
                ]
                if len(targets) != 1:
                    raise GraphError("Missing fork branch")
                seen = set()

                def branch_walk(item):
                    if item == cfg["join_id"] or item in seen:
                        return
                    seen.add(item)
                    if not adjacency[item]:
                        raise GraphError("Every fork branch must reach its join")
                    for target in adjacency[item]:
                        branch_walk(target)

                branch_walk(targets[0])
                branch_sets.append(seen)
            for i, left in enumerate(branch_sets):
                for right in branch_sets[i + 1 :]:
                    if left & right:
                        raise GraphError("Branches may meet only at their paired join")
                    ltypes = {by_id[x]["type"] for x in left} & MUTATIONS
                    rtypes = {by_id[x]["type"] for x in right} & MUTATIONS
                    if ltypes & rtypes:
                        raise GraphError("Conflicting parallel writes")
        elif kind == "join":
            if (
                by_id.get(cfg.get("fork_id"), {}).get("config", {}).get("join_id")
                != nid
            ):
                raise GraphError("Unpaired join")
        if any((nid, port) not in connections for port in required):
            raise GraphError(f"Missing output for {nid}")
    if not any(n["type"] == "complete" for n in nodes):
        raise GraphError("Completion node required")
    return graph


def default_graph(profile_code="local-analysis"):
    kinds = [
        "entry",
        "validation",
        "normalization",
        "fingerprint",
        "playbook",
        "knowledge_base",
        "correlation",
        "llm_analysis",
        "complete",
    ]
    nodes = [
        {
            "id": kind,
            "type": kind,
            "config": {"profile_code": profile_code} if kind == "llm_analysis" else {},
            "position": {"x": i * 220, "y": 60},
        }
        for i, kind in enumerate(kinds)
    ]
    nodes.append(
        {
            "id": "dlq",
            "type": "dead_letter",
            "config": {},
            "position": {"x": 600, "y": 300},
        }
    )
    edges = [
        {"id": f"e{i}", "source": a, "target": b, "sourceHandle": "success"}
        for i, (a, b) in enumerate(zip(kinds, kinds[1:]))
    ]
    edges += [
        {"id": f"err-{kind}", "source": kind, "target": "dlq", "sourceHandle": "error"}
        for kind in kinds[1:-1]
    ]
    return {"format_version": "1.0", "nodes": nodes, "edges": edges}
