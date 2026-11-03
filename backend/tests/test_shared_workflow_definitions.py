from copy import deepcopy
from datetime import datetime, timezone

import pytest
from tierx_workflows.definitions import compile_bundle, validate_definition
from tierx_workflows.graph import GraphError, validate_graph


def graph(*middle, capabilities=None):
    nodes = [{"id": "entry", "type": "entry", "config": {}}, *middle,
             {"id": "done", "type": "complete", "config": {}}]
    return {"format_version": "2.0", "input_capabilities": capabilities or ["raw"],
            "nodes": nodes, "edges": [{"id": f"e{i}", "source": a["id"], "target": b["id"]}
                                       for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}


def row(kind, code, configuration, revision=1, tenants=None):
    return {"kind": kind, "code": code, "revision": revision, "name": code,
            "tenant_ids": tenants or ["one"], "enabled": True, "configuration": configuration}


def test_mapping_and_analysis_need_data_not_locked_validation_or_correlation():
    value = graph({"id": "map", "type": "normalization", "config": {"field_mapping": {"host.name": "host"}}},
                  {"id": "analysis", "type": "llm_analysis", "config": {"profile_code": "local"}})
    assert validate_graph(value) == value
    with pytest.raises(GraphError):
        validate_graph(graph({"id": "analysis", "type": "llm_analysis", "config": {"profile_code": "local"}}))
    with pytest.raises(GraphError):
        validate_definition("workflow", graph(capabilities=["normalization"]))


def test_bundle_pins_dependencies_and_checks_tenant_grants_and_cycles():
    root = row("workflow", "root", graph(
        {"id": "map", "type": "normalization", "config": {"field_mapping": {"host.name": "host"}}},
        {"id": "pb", "type": "playbook_call", "config": {"definition_code": "investigate"}}))
    child = row("playbook", "investigate", graph(capabilities=["normalization"]), revision=3)
    source = {("playbook", "investigate"): child}
    def resolve(kind, code, revision):
        return deepcopy(source[kind, code])
    bundle = compile_bundle(root, resolve, "one", lambda _: {"at": datetime.now(timezone.utc)})
    assert bundle["definitions"][bundle["root"]]["references"]["pb"] == "playbook:investigate@3"
    source["playbook", "investigate"]["revision"] = 4
    assert "playbook:investigate@3" in bundle["definitions"]
    child["tenant_ids"] = ["two"]
    with pytest.raises(GraphError, match="authorized"):
        compile_bundle(root, resolve, "one", lambda _: {})
    child["tenant_ids"] = ["one"]
    child["configuration"] = graph({"id": "self", "type": "playbook_call", "config": {"definition_code": "investigate"}}, capabilities=["normalization"])
    with pytest.raises(GraphError, match="Recursive"):
        compile_bundle(root, resolve, "one", lambda _: {})


def test_agent_and_selector_budgets_and_fallback_are_validated():
    agent = {"profile_code": "local", "prompt": "Investigate supplied evidence.", "tools": ["connector:demo:observe", "agent:network"]}
    assert validate_definition("agent", agent)["max_calls"] == 10
    with pytest.raises(GraphError):
        validate_definition("agent", {**agent, "max_calls": 999})
    with pytest.raises(GraphError):
        validate_graph(graph({"id": "select", "type": "playbook_selector", "config": {"candidates": ["network"]}}, capabilities=["normalization"]))
