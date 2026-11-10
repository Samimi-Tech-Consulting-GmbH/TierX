from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import mongomock
import pytest
from tierx_workflows.graph import checksum
from app.workflows.engine import Engine
from app.workflows.runtime import WorkflowTools, reserve
from app.workflows.storage import WorkflowDatabase
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
    db, platform = WorkflowDatabase(Database(mongo.tenant)), Database(mongo.platform)
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
    assert mongo.tenant.alerts.count_documents({}) == 1
    assert mongo.tenant.v2_alerts.count_documents({}) == 0
    assert all("wait_reason" not in job for job in mongo.tenant.v2_jobs.find({"state": "SUCCEEDED"}))


@pytest.mark.asyncio
async def test_correlation_shares_pool_but_does_not_overwrite_analyses(environment):
    mongo, db = environment
    tools = WorkflowTools()
    for identity in ["a", "b", "isolated"]:
        mongo.tenant.alerts.insert_one({"alert_id": identity, "workflow_format": "2.0", "tenant_id": "one",
            "created_at": datetime.now(timezone.utc), "normalized_payload": {"source.ip": "192.0.2.1"},
            "alert_analysis": {"result": identity}, "status": "ANALYZED"})
        mongo.tenant.v2_jobs.insert_one({"job_id": identity})
        alert = mongo.tenant.alerts.find_one({"alert_id": identity})
        await tools.correlate(db, {"tenant_id": "one"}, node("c", "correlation", group="other" if identity == "isolated" else None), {"job_id": identity}, alert)
    first, second, isolated = [mongo.tenant.alerts.find_one({"alert_id": key}) for key in ["a", "b", "isolated"]]
    assert first["cluster_id"] == second["cluster_id"] != isolated["cluster_id"]
    assert first["clustering_status"] == second["clustering_status"] == "CORRELATED"
    assert first["alert_analysis"] == {"result": "a"}
    assert first["status"] == "ANALYZED"
    assert second["correlation_result"]["correlated_alert_ids"] == ["a"]
    assert mongo.tenant.clusters.count_documents({}) == 2


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
    mongo.tenant.alerts.insert_one({"alert_id": "r", "normalized_payload": {"host.name": "synthetic"}})
    mongo.tenant.v2_jobs.insert_one({"job_id": "model", "state": "SUCCEEDED", "output": {"result": {"headline": "Evidence-based result"}}})
    output, _ = await WorkflowTools().execute(db, parent, node("save", "persist_analysis", input_path="nodes.model.output.result"),
        {"job_id": "persist", "ancestors": {"model": {"job_id": "model", "state": "SUCCEEDED"}}})
    assert output["state"] == "SUCCEEDED"
    assert mongo.tenant.alerts.find_one({"alert_id": "r"})["alert_analysis"]["headline"] == "Evidence-based result"
    assert mongo.tenant.clusters.count_documents({}) == 0
    assert mongo.tenant.v2_alert_analyses.count_documents({}) == 1


@pytest.mark.asyncio
async def test_waiting_selector_reuses_its_first_persisted_fallback(environment, monkeypatch):
    from app.workflows import runtime
    from app.workflows.tools import NodeWaiting
    mongo,db=environment
    mongo.tenant.v2_jobs.insert_one({"job_id":"selector"})
    tools=WorkflowTools()
    tools.profile=AsyncMock(return_value=({},None))
    tools.model_call=AsyncMock(side_effect=TimeoutError())
    invoke=AsyncMock(side_effect=NodeWaiting("SUBFLOW_RUNNING"))
    monkeypatch.setattr(runtime,"invoke",invoke)
    definition={"references":{"select:playbook:fallback":"playbook:fallback@1","select:playbook:other":"playbook:other@1"}}
    parent=run(linear([node("entry","entry"),node("done","complete")]))
    parent["bundle"]["definitions"]["playbook:other@1"]={"description":"Other"}
    selector=node("select","playbook_selector",mode="model",profile_code="model",candidates=["other"],fallback="fallback")
    alert={"alert_type":"synthetic","normalized_payload":{}}
    for _ in range(2):
        with pytest.raises(NodeWaiting):
            await tools.select(db,parent,selector,{"job_id":"selector"},alert,definition)
    assert tools.model_call.await_count==1
    assert all(call.args[3]=="playbook:fallback@1" for call in invoke.await_args_list)


@pytest.mark.asyncio
async def test_failed_reasoning_has_terminal_analysis_status_and_safe_snapshots(environment):
    mongo,db=environment
    parent=run(linear([node("entry","entry"),node("map","normalization",field_mapping={"host.name":"host"}),
        node("reason","llm_analysis",profile_code="missing"),node("done","complete")]))
    result=await drive(mongo,db,parent)
    assert result["state"]=="FAILED"
    alert=mongo.tenant.alerts.find_one({"alert_id":"r"})
    assert alert["analysis_status"]=="FAILED"
    job=mongo.tenant.v2_jobs.find_one({"node_id":"reason"})
    assert job["input_snapshot"]["value"]["normalized_payload"]=={"host.name":"synthetic"}
    assert "raw_payload" not in str(job["input_snapshot"])
    assert job["definition_ref"]=="workflow:root@1"
    assert job["attempt_count"]==1


@pytest.mark.asyncio
async def test_failure_before_reasoning_finalizes_alert(environment):
    mongo, db = environment
    parent = run(linear([node("entry", "entry"), node("validate", "validation"), node("done", "complete")]))
    result = await drive(mongo, db, parent)
    assert result["state"] == "FAILED"
    alert = mongo.tenant.alerts.find_one({"alert_id": "r"})
    assert alert["analysis_status"] == "FAILED"
    assert alert["status"] == "ERROR"


@pytest.mark.asyncio
async def test_cancelled_alert_cannot_restart_reasoning_or_commit_analysis(environment):
    mongo, db = environment
    parent = run(linear([node("entry", "entry"), node("done", "complete")]))
    mongo.tenant.v2_runs.insert_one(deepcopy(parent))
    mongo.tenant.alerts.insert_one({"alert_id": "r", "workflow_state": "CANCELLED", "analysis_status": "FAILED"})
    tools = WorkflowTools()
    tools.profile = AsyncMock()
    with pytest.raises(NodeFailure, match="ROOT_RUN_TERMINAL"):
        await tools.reason(db, parent, node("reason", "llm_analysis", profile_code="model"), {"job_id": "reason"}, {"alert_id": "r"})
    tools.profile.assert_not_awaited()
    assert mongo.tenant.alerts.find_one({})["analysis_status"] == "FAILED"
    # Do not insert a new analysis history item when the root is already cancelled.
    mongo.tenant.v2_runs.update_one({"run_id": "r"}, {"$set": {"state": "CANCELLED"}})
    tools.context = AsyncMock(return_value={"analysis": {"headline": "Late result"}})
    with pytest.raises(NodeFailure, match="ROOT_RUN_CANCELLED"):
        await tools.execute(db, parent, node("persist", "persist_analysis", input_path="analysis"), {"job_id": "persist"})
    assert "alert_analysis" not in mongo.tenant.alerts.find_one({})
    assert mongo.tenant.v2_alert_analyses.count_documents({}) == 0


@pytest.mark.asyncio
async def test_cancellation_between_root_check_and_history_write_marks_discarded(environment, monkeypatch):
    mongo, db = environment
    parent = run(linear([node("entry", "entry"), node("done", "complete")]))
    mongo.tenant.v2_runs.insert_one(deepcopy(parent))
    mongo.tenant.alerts.insert_one({"alert_id": "r", "workflow_state": "RUNNING"})
    tools = WorkflowTools()
    tools.context = AsyncMock(return_value={"analysis": {"headline": "Late result"}})
    original = mongo.tenant.v2_alert_analyses.update_one
    def cancel_then_insert(query, update, **kwargs):
        if "$setOnInsert" in update:
            mongo.tenant.v2_runs.update_one({"run_id": "r"}, {"$set": {"state": "CANCELLED"}})
            mongo.tenant.alerts.update_one({"alert_id": "r"}, {"$set": {"workflow_state": "CANCELLED"}})
        return original(query, update, **kwargs)
    monkeypatch.setattr(mongo.tenant.v2_alert_analyses, "update_one", cancel_then_insert)
    with pytest.raises(NodeFailure, match="ROOT_RUN_CANCELLED"):
        await tools.execute(db, parent, node("persist", "persist_analysis", input_path="analysis"), {"job_id": "persist"})
    assert "alert_analysis" not in mongo.tenant.alerts.find_one({})
    history = mongo.tenant.v2_alert_analyses.find_one({})
    assert history["persistence_state"] == "DISCARDED"
    assert history["discard_reason"] == "ROOT_RUN_CANCELLED"


@pytest.mark.asyncio
async def test_missing_root_at_persistence_is_structured_failure(environment):
    mongo, db = environment
    parent = run(linear([node("entry", "entry"), node("done", "complete")]))
    mongo.tenant.alerts.insert_one({"alert_id": "r"})
    tools = WorkflowTools()
    tools.context = AsyncMock(return_value={"analysis": {"headline": "Result"}})
    with pytest.raises(NodeFailure, match="ROOT_RUN_MISSING"):
        await tools.execute(db, parent, node("persist", "persist_analysis", input_path="analysis"), {"job_id": "persist"})
    assert mongo.tenant.v2_alert_analyses.count_documents({}) == 0


@pytest.mark.asyncio
async def test_waiting_worker_cannot_revive_cancelled_job(environment):
    from app.workflows.tools import NodeWaiting
    mongo, db = environment
    engine = Engine()
    parent = run(linear([node("entry", "entry"), node("done", "complete")]))
    mongo.tenant.v2_runs.insert_one(deepcopy(parent))
    job = {"job_id": "j", "run_id": "r", "node_id": "entry", "state": "RUNNING", "lease_owner": engine.owner}
    mongo.tenant.v2_jobs.insert_one(dict(job))
    async def cancelled_during_call(*args):
        mongo.tenant.v2_jobs.update_one({"job_id": "j"}, {"$set": {"state": "CANCELLED", "routed": True}})
        raise NodeWaiting("SUBFLOW_RUNNING")
    engine.tools.execute = cancelled_during_call
    await engine.execute(db, job)
    assert mongo.tenant.v2_jobs.find_one({"job_id": "j"})["state"] == "CANCELLED"


@pytest.mark.asyncio
async def test_real_http_tool_agent_and_alert_owned_result(environment, monkeypatch, tmp_path):
    """Real REST/MCP HTTP protocol fixture, deliberately not a real LLM."""
    import base64
    import importlib.util
    from pathlib import Path
    from threading import Thread
    from http.server import ThreadingHTTPServer
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from app.workflows import runtime
    spec = importlib.util.spec_from_file_location("synthetic_provider", Path(__file__).resolve().parents[2] / "examples/workflow-providers/server.py")
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    monkeypatch.setenv("EXAMPLE_PROVIDER_TOKEN", "synthetic-protocol-test")
    monkeypatch.setenv("EXAMPLE_DB", str(tmp_path / "deliveries.sqlite"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), provider.Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("TIERX_V2_LOCAL_CONNECTOR_ORIGINS", origin)
    encoded = base64.urlsafe_b64encode(b"s" * 32).decode()
    monkeypatch.setattr(runtime.settings, "webhook_secret_encryption_key", encoded)
    nonce = b"n" * 12
    mongo, db = environment
    connector = {"connector_code": "assets", "kind": "mcp", "url": origin + "/mcp", "timeout_seconds": 5,
        "tenant_ids": ["one"], "enabled": True, "tools": [{"name": "asset_context", "description": "Synthetic assets",
        "input_schema": provider.INPUT, "output_schema": provider.OUTPUT, "retry_safe": True}]}
    mongo.platform.v2_connectors.insert_one({**connector, "credentials": {"nonce": nonce.hex(),
        "ciphertext": AESGCM(b"s" * 32).encrypt(nonce, b"synthetic-protocol-test", b"tierx:connector:v1:assets").hex()}})
    profile = {"provider": "openai", "base_url": origin + "/v1", "model": "synthetic-protocol-fixture", "profile_code": "synthetic",
        "revision": 1, "tool_mode": "native", "timeout_seconds": 5}
    async def configured_profile(self, run, code):
        return profile, "synthetic-protocol-test"
    monkeypatch.setattr(WorkflowTools, "profile", configured_profile)
    schema = {"type": "object", "properties": {"headline": {"type": "string"}}, "required": ["headline"], "additionalProperties": False}
    graph = linear([node("entry", "entry"), node("map", "normalization", field_mapping={"host.name": "host"}),
        node("agent", "llm_tools", profile_code="synthetic", tools=["connector:assets:asset_context"], output_schema=schema),
        node("save", "persist_analysis", input_path="nodes.agent.output"), node("notify", "notify_jira"), node("done", "complete")])
    parent = run(graph)
    parent["resources"]["connectors"] = {"assets": connector}
    try:
        result = await drive(mongo, db, parent)
        assert result["state"] == "SUCCEEDED", result
        alert = mongo.tenant.alerts.find_one({"alert_id": "r"})
        assert alert["status"] == "ANALYZED"
        assert alert["alert_analysis"]["model"] == "synthetic-protocol-fixture"
        assert mongo.tenant.v2_tool_calls.count_documents({"state": "SUCCEEDED"}) == 1
        assert mongo.tenant.v2_model_calls.count_documents({}) == 2
        assert mongo.tenant.v2_jobs.find_one({"node_id": "notify"})["output"]["state"] == "SKIPPED"
        assert not alert.get("cluster_id")
    finally:
        server.shutdown()
        server.server_close()
