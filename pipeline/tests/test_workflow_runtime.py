from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import mongomock
import pytest
from tierx_workflows.graph import checksum
from app.workflows.engine import Engine
from app.workflows.runtime import WorkflowTools, reserve
from app.workflows.tools import NodeFailure
from workflow_database import Database


def linear(nodes, capabilities=None):
    return {"format_version": "2.0", "input_capabilities": capabilities or ["raw"], "nodes": nodes,
            "edges": [{"id": str(i), "source": a["id"], "target": b["id"]} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}


def node(identity, kind, **config):
    return {"id": identity, "type": kind, "config": config}


@pytest.fixture
def environment(monkeypatch):
    from app.workflows import runtime
    mongo = mongomock.MongoClient(tz_aware=True)
    db, platform = Database(mongo.tenant), Database(mongo.platform)
    monkeypatch.setattr(runtime, "get_database", lambda: platform)
    mongo.platform.workflow_definitions.insert_many([
        {"kind": kind, "code": code, "enabled": True, "tenant_ids": ["one"]}
        for kind, code in [("workflow", "root"), ("playbook", "investigate"), ("agent", "network")]])
    return mongo, db


def run(graph, identity="r"):
    definition = {"kind": "workflow", "code": "root", "revision": 1, "graph": graph, "references": {}, "resources": {}}
    return {"run_id": identity, "root_run_id": identity, "alert_id": identity, "tenant_id": "one",
            "cohort": "workflow-runtime", "state": "PENDING", "created_at": datetime.now(timezone.utc),
            "graph": graph, "definition_ref": "workflow:root@1", "bundle": {"root": "workflow:root@1", "definitions": {"workflow:root@1": definition}},
            "resources": {}, "release_version": "0.2.8", "release_sha": "a" * 40,
            "input": {"alert_type": "synthetic", "source_system": "SPLUNK", "raw_payload": {"host": "synthetic"}}}


async def drive(mongo, db, root):
    engine = Engine()
    mongo.tenant.v2_runs.insert_one(deepcopy(root))
    for _ in range(30):
        for record in list(mongo.tenant.v2_runs.find({"state": "PENDING"})):
            await engine.initialize(db, record)
        for record in list(mongo.tenant.v2_jobs.find({"state": {"$in": ["PENDING", "WAITING"]}})):
            mongo.tenant.v2_jobs.update_one({"job_id": record["job_id"]}, {"$set": {"state": "RUNNING", "lease_owner": engine.owner}})
            record["lease_owner"] = engine.owner
            await engine.execute(db, record)
        for record in list(mongo.tenant.v2_jobs.find({"state": {"$in": ["SUCCEEDED", "FAILED"]}, "routed": False})):
            await engine.route(db, record)
        result = mongo.tenant.v2_runs.find_one({"run_id": root["run_id"]})
        if result["state"] not in {"PENDING", "RUNNING"}:
            return result
    raise AssertionError("Workflow did not finish")


@pytest.mark.asyncio
async def test_nested_playbook_releases_parent_and_returns_output(environment):
    mongo, db = environment
    parent = run(linear([node("entry", "entry"), node("map", "normalization", field_mapping={"host.name": "host"}),
                         node("pb", "playbook_call", definition_code="investigate"),
                         node("done", "complete", output_path="nodes.pb.output.result")]))
    child = {"kind": "playbook", "code": "investigate", "revision": 2,
             "graph": linear([node("entry", "entry"), node("done", "complete", output_path="alert.normalized_payload")], ["normalization"]),
             "references": {}, "resources": {}}
    parent["bundle"]["definitions"]["playbook:investigate@2"] = child
    parent["bundle"]["definitions"]["workflow:root@1"]["references"]["pb"] = "playbook:investigate@2"
    result = await drive(mongo, db, parent)
    assert result["state"] == "SUCCEEDED"
    assert result["output"] == {"host.name": "synthetic"}
    assert mongo.tenant.v2_runs.count_documents({}) == 2
    assert mongo.tenant.alerts.count_documents({}) == 0


@pytest.mark.asyncio
async def test_correlation_shares_pool_but_does_not_overwrite_analyses(environment):
    mongo, db = environment
    tools = WorkflowTools()
    for identity in ["a", "b", "isolated"]:
        mongo.tenant.v2_alerts.insert_one({"alert_id": identity, "workflow_format": "2.0", "tenant_id": "one",
            "created_at": datetime.now(timezone.utc), "normalized_payload": {"source.ip": "192.0.2.1"},
            "alert_analysis": {"result": identity}, "status": "ANALYZED"})
        mongo.tenant.v2_jobs.insert_one({"job_id": identity})
        alert = mongo.tenant.v2_alerts.find_one({"alert_id": identity})
        await tools.correlate(db, {"tenant_id": "one"}, node("c", "correlation", group="other" if identity == "isolated" else None), {"job_id": identity}, alert)
    first, second, isolated = [mongo.tenant.v2_alerts.find_one({"alert_id": key}) for key in ["a", "b", "isolated"]]
    assert first["cluster_id"] == second["cluster_id"] != isolated["cluster_id"]
    assert first["clustering_status"] == second["clustering_status"] == "CORRELATED"
    assert first["alert_analysis"] == {"result": "a"}
    assert first["status"] == "ANALYZED"
    assert second["correlation_result"]["correlated_alert_ids"] == ["a"]
    assert mongo.tenant.v2_clusters.count_documents({}) == 2


@pytest.mark.asyncio
async def test_call_budget_is_durable_idempotent_and_tenant_local(environment):
    _, db = environment
    parent = {"run_id": "r", "root_run_id": "r", "max_calls": 1}
    await reserve(db, parent, "one")
    await reserve(db, parent, "one")
    with pytest.raises(NodeFailure, match="BUDGET"):
        await reserve(db, parent, "two")


@pytest.mark.asyncio
async def test_analysis_persistence_is_alert_owned_and_preserves_history(environment):
    mongo, db = environment
    graph = linear([node("entry", "entry"), node("done", "complete")])
    parent = run(graph)
    parent["state"] = "RUNNING"
    mongo.tenant.v2_runs.insert_one(deepcopy(parent))
    mongo.tenant.v2_alerts.insert_one({"alert_id": "r", "normalized_payload": {"host.name": "synthetic"}})
    mongo.tenant.v2_jobs.insert_one({"job_id": "model", "state": "SUCCEEDED", "output": {"result": {"headline": "Evidence-based result"}}})
    output, _ = await WorkflowTools().execute(db, parent, node("save", "persist_analysis", input_path="nodes.model.output.result"),
        {"job_id": "persist", "ancestors": {"model": {"job_id": "model", "state": "SUCCEEDED"}}})
    assert output["state"] == "SUCCEEDED"
    assert mongo.tenant.v2_alerts.find_one({"alert_id": "r"})["alert_analysis"]["result"]["headline"] == "Evidence-based result"
    assert mongo.tenant.v2_clusters.count_documents({}) == 0
    assert mongo.tenant.v2_alert_analyses.count_documents({}) == 1
