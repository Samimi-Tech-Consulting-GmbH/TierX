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


@pytest.mark.parametrize("mode,expected", [("static",{"mapped","fallback"}), ("model",{"mapped","candidate","fallback"}), ("model_only",{"candidate","fallback"})])
def test_router_compiles_only_dependencies_used_by_mode(mode, expected):
    from tierx_workflows.definitions import references
    config={"mode":mode,"mappings":{"synthetic":"mapped"},"candidates":["candidate"],"fallback":"fallback","profile_code":"local"}
    value=graph({"id":"select","type":"playbook_selector","config":config},capabilities=["normalization"])
    validate_graph(value)
    assert {item[2] for item in references("playbook",value)} == expected
    if mode == "model_only":
        del config["profile_code"]
        with pytest.raises(GraphError,match="profile"):
            validate_graph(value)


def test_editable_templates_validate_without_installing_resources():
    from tierx_workflows.templates import templates
    from tierx_workflows.definitions import validate_definition
    for template in templates():
        validate_definition(template["kind"], template["configuration"])


def test_cached_dependency_cannot_hide_excessive_depth():
    def sub(code, children):
        return row("playbook",code,graph(*[{"id":"call"+str(index),"type":"playbook_call","config":{"definition_code":child}} for index,child in enumerate(children)],capabilities=["normalization"]))
    entries={code:sub(code,children) for code,children in {"a":["d"],"b":["c"],"c":["a"],"d":[]}.items()}
    root=row("workflow","root",graph({"id":"map","type":"normalization","config":{"field_mapping":{"host.name":"host"}}},
        {"id":"a","type":"playbook_call","config":{"definition_code":"a"}}, {"id":"b","type":"playbook_call","config":{"definition_code":"b"}}))
    with pytest.raises(GraphError,match="three nested"):
        compile_bundle(root,lambda kind,code,revision:entries[code],"one",lambda _: {})


def test_modern_nodes_and_connector_tools_are_rejected_in_legacy_graphs():
    value=graph({"id":"tool","type":"tool_call","config":{"connector_code":"assets","tool_name":"observe"}})
    value["format_version"]="1.0"
    with pytest.raises(GraphError,match="format 2.0"):
        validate_graph(value)


@pytest.mark.parametrize("mode,extra", [("static",{"candidates":[""]*30,"profile_code":"invalid profile","threshold":-1}), ("model_only",{"mappings":{"x":""}})])
def test_router_ignores_invalid_hidden_settings(mode, extra):
    config={"mode":mode,"fallback":"generic","profile_code":"local",**extra}
    result=validate_graph(graph({"id":"pick","type":"playbook_selector","config":config},capabilities=["normalization"]))
    cleaned=next(n["config"] for n in result["nodes"] if n["id"]=="pick")
    assert ("candidates" if mode=="static" else "mappings") not in cleaned


def test_static_router_does_not_resolve_stale_profile(monkeypatch):
    from app.api.v2 import workflows
    monkeypatch.setattr(workflows.DatabaseManager,"get_tenant_database",lambda _: object())
    result=workflows.resources(None,{"nodes":[{"type":"playbook_selector","config":{"mode":"static","profile_code":"unauthorized"}}]},"one")
    assert result["profiles"]=={}
