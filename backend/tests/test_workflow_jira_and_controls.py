from app.api.dependencies.auth import get_current_user
from app.api.v1.jira_integrations import require_jira_integration
from app.api.v2 import definitions, entrypoints, run_controls, workflows
from test_workflows_v2 import setup, minimal


def prepare(setup, monkeypatch):
    client, mongo, user = setup
    monkeypatch.setenv("TIERX_WORKFLOW_ENGINE_ENABLED", "true")
    monkeypatch.setattr(entrypoints, "Tenant", workflows.Tenant)
    user.role = "PLATFORM_ADMIN"
    client.app.include_router(definitions.router, prefix="/api/v2")
    client.app.include_router(entrypoints.router, prefix="/api/v2")
    client.app.include_router(run_controls.router, prefix="/api/v2")
    graph = minimal()
    graph["format_version"] = "2.0"
    graph["nodes"][0]["config"] = {"input_mode": "raw", "source_system": "SPLUNK", "alert_type": "synthetic", "timestamp_path": "result._time"}
    path = "/api/v2/admin/workflow-definitions/workflow/raw"
    assert client.put(path, json={"name": "Raw", "tenant_ids": ["one"], "configuration": graph}).status_code == 200
    assert client.post(path + "/publish").status_code == 200
    integration = {"integration_id": "jira-one", "state": "ACTIVE", "name": "Synthetic Jira", "jira_cloud_id": "cloud-one", "jira_site_url": "https://example.atlassian.net"}
    mongo.soc_mind_platform.jira_integrations.insert_one(dict(integration))
    assert client.post(path + "/entry-credentials", json={"tenant_id": "one", "jira_connection_ids": ["jira-one"]}).status_code == 200
    client.app.dependency_overrides[require_jira_integration] = lambda: integration
    return client, mongo, user


def test_jira_workflow_identity_idempotency_and_explicit_delivery(setup, monkeypatch):
    client, mongo, _ = prepare(setup, monkeypatch)
    path = "/api/v2/workflows/raw/tenants/one/jira"
    assert client.get(path + "/connection").json()["jira_cloud_id"] == "cloud-one"
    body = {"jira_cloud_id": "cloud-one", "jira_site_url": "https://example.atlassian.net", "project_key": "TEST",
        "issue_id": "1", "issue_key": "TEST-1", "issue_created_at": "2026-01-01T00:00:00Z", "issue_updated_at": "2026-01-01T00:00:00Z",
        "submitted_by": {"account_id": "synthetic"}, "raw_alert": {"result": {"_time": "2026-01-01T00:00:00Z", "host": "synthetic"}},
        "raw_alert_source": {"kind": "DESCRIPTION", "sha256": "a" * 64}}
    accepted = client.post(path + "/submissions", json=body)
    assert accepted.status_code == 202, accepted.text
    row = accepted.json()
    assert row["trace_path"] == f"/dashboard/one/workflows/runs/{row['run_id']}"
    repeated = client.post(path + "/submissions", json=body).json()
    assert repeated["alert_id"] == row["alert_id"]
    run = mongo.tenant_one.v2_runs.find_one({})
    assert run["input"]["raw_payload"] == body["raw_alert"]
    assert run["source_reference"]["issue_key"] == "TEST-1"
    endpoint = path + "/submissions/" + row["submission_id"]
    mongo.tenant_one.v2_runs.update_one({"run_id": row["run_id"]}, {"$set": {"state": "SUCCEEDED"}})
    assert client.get(endpoint).json()["state"] == "COMPLETED"
    assert client.get(endpoint).json()["trace_path"] == f"/dashboard/one/workflows/runs/{row['run_id']}"
    assert client.post(endpoint + "/comments", json={"kind": "FINAL", "jira_comment_id": "2"}).status_code == 409
    mongo.soc_mind_platform.workflow_jira_deliveries.insert_one({"_id": "d", "submission_id": row["submission_id"], "integration_id": "jira-one", "state": "PENDING", "analysis": {"headline": "Synthetic analysis"}})
    assert client.get(endpoint).json()["result"]["headline"] == "Synthetic analysis"
    assert client.post(endpoint + "/comments", json={"kind": "FINAL", "jira_comment_id": "2", "delivery_id": "d"}).json()["state"] == "COMPLETED"
    assert client.post(path + "/submissions", json={**body, "jira_cloud_id": "another-cloud"}).status_code == 403
    assert client.get("/api/v2/workflows/raw/tenants/two/jira/connection").status_code == 403


def test_workflow_controls_and_feedback_do_not_change_verdict(setup, monkeypatch):
    client, mongo, user = prepare(setup, monkeypatch)
    db = mongo.tenant_one
    db.alerts.insert_one({"alert_id": "a", "run_id": "r", "verdict": "INCONCLUSIVE"})
    db.v2_runs.insert_many([{"run_id": "r", "root_run_id": "r", "state": "RUNNING", "alert_id": "a"},
        {"run_id": "child", "root_run_id": "r", "state": "RUNNING", "alert_id": "a"}])
    db.v2_jobs.insert_one({"job_id": "j", "run_id": "child", "state": "RUNNING"})
    assert client.post("/api/v2/tenants/one/runs/r/cancel").status_code == 200
    assert db.v2_runs.count_documents({"state": "CANCELLED"}) == 2
    assert db.v2_jobs.find_one({})["state"] == "CANCELLED"
    assert db.alerts.find_one({"alert_id": "a"})["analysis_status"] == "FAILED"
    user.role, user.tenant_id = "TENANT_OPERATOR", "one"
    response = client.post("/api/v2/tenants/one/alerts/a/feedback", json={"decision": "CORRECT", "verdict": "FALSE_POSITIVE"})
    assert response.status_code == 201, response.text
    assert db.alerts.find_one({"alert_id": "a"})["verdict"] == "INCONCLUSIVE"
    assert client.put("/api/v2/tenants/one/alerts/a/decision", json={"verdict": "FALSE_POSITIVE", "rationale": "Synthetic reviewed evidence"}).status_code == 200
    assert db.alerts.find_one({"alert_id": "a"})["verdict"] == "FALSE_POSITIVE"
    assert db.workflow_analyst_decisions.count_documents({}) == 1
    assert client.post("/api/v2/tenants/one/runs/r/cancel").status_code == 403
    assert client.get("/api/v2/tenants/two/alerts/a/feedback").status_code == 403


def test_preparation_is_available_before_cutover_and_debug_reports_pinned_versions(setup, monkeypatch):
    client,mongo,user=prepare(setup,monkeypatch)
    monkeypatch.setenv("TIERX_WORKFLOW_ENGINE_ENABLED","false")
    monkeypatch.setenv("TIERX_INGESTION_V2_ENABLED","false")
    assert client.get("/api/v2/admin/workflow-definitions").status_code==200
    assert client.get("/api/v2/admin/llm-profiles").status_code==200
    assert client.post("/api/v2/workflows/raw/tenants/one/ingest",json={}).status_code==404
    monkeypatch.setenv("TIERX_WORKFLOW_ENGINE_ENABLED","true")
    root=mongo.tenant_one.v2_revisions.find_one({"flow_id":"workflow:raw"})
    mongo.tenant_one.v2_runs.insert_one({"run_id":"debug","root_run_id":"debug","alert_id":"a","tenant_id":"one","state":"RUNNING",
        "definition_code":"raw","definition_ref":"workflow:raw@1","revision":1,"graph":root["graph"],"bundle":root["bundle"]})
    result=client.get("/api/v2/tenants/one/runs/debug").json()
    assert result["workflow_version"]["definition_ref"]=="workflow:raw@1"
    assert len(result["nodes"])==2
    assert all(node["state"]=="NOT_REACHED" for node in result["nodes"])
    assert "bundle" not in result


def test_cancel_terminal_root_never_changes_alert_or_children(setup, monkeypatch):
    client, mongo, _ = prepare(setup, monkeypatch)
    db = mongo.tenant_one
    db.v2_runs.insert_many([
        {"run_id": "root", "state": "SUCCEEDED", "alert_id": "a"},
        {"run_id": "child", "root_run_id": "root", "state": "RUNNING", "alert_id": "a"},
    ])
    db.alerts.insert_one({"alert_id": "a", "run_id": "root", "workflow_state": "SUCCEEDED", "analysis_status": "SUCCEEDED"})
    assert client.post("/api/v2/tenants/one/runs/child/cancel").status_code == 409
    assert db.v2_runs.find_one({"run_id": "child"})["state"] == "RUNNING"
    assert db.alerts.find_one({})["workflow_state"] == "SUCCEEDED"


def test_completion_racing_cancellation_wins_without_alert_mutation(setup, monkeypatch):
    client, mongo, _ = prepare(setup, monkeypatch)
    db = mongo.tenant_one
    db.v2_runs.insert_one({"run_id": "r", "state": "RUNNING", "alert_id": "a"})
    db.alerts.insert_one({"alert_id": "a", "run_id": "r", "workflow_state": "SUCCEEDED"})
    original = db.v2_runs.find_one_and_update
    def complete_first(query, update, **kwargs):
        db.v2_runs.update_one({"run_id": "r"}, {"$set": {"state": "SUCCEEDED"}})
        return original(query, update, **kwargs)
    monkeypatch.setattr(db.v2_runs, "find_one_and_update", complete_first)
    assert client.post("/api/v2/tenants/one/runs/r/cancel").status_code == 409
    assert db.alerts.find_one({})["workflow_state"] == "SUCCEEDED"


def test_acceptance_environment_cannot_inherit_remote_database(monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("workflow_acceptance", Path(__file__).resolve().parents[2] / "examples/workflow-sandbox/acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("TIERX_MONGO_URL", "mongodb://remote.invalid/")
    monkeypatch.setenv("SOC_MIND_MONGO_URL", "mongodb://legacy.invalid/")
    env = module.local_environment()
    assert env["MONGO_URL"] == env["TIERX_MONGO_URL"] == "mongodb://127.0.0.1:27028/"
    assert "SOC_MIND_MONGO_URL" not in env


def test_cancel_preserves_previously_persisted_success(setup, monkeypatch):
    client, mongo, _ = prepare(setup, monkeypatch)
    db = mongo.tenant_one
    db.v2_runs.insert_one({"run_id": "root", "state": "RUNNING", "alert_id": "a"})
    db.alerts.insert_one({"alert_id": "a", "run_id": "root", "analysis_status": "SUCCEEDED", "status": "ANALYZED", "alert_analysis": {"headline": "Saved"}})
    assert client.post("/api/v2/tenants/one/runs/root/cancel").status_code == 200
    alert = db.alerts.find_one({})
    assert alert["workflow_state"] == "CANCELLED"
    assert alert["analysis_status"] == "SUCCEEDED"
    assert alert["alert_analysis"]["headline"] == "Saved"


def test_debug_uses_bounded_snapshots_and_metadata_lists_exclude_outputs(setup, monkeypatch):
    client, mongo, _ = prepare(setup, monkeypatch)
    db = mongo.tenant_one
    graph = minimal()
    graph["format_version"] = "2.0"
    db.v2_runs.insert_one({"run_id": "r", "root_run_id": "r", "alert_id": "a", "state": "SUCCEEDED", "graph": graph,
        "output": {"context": "PRIVATE EVIDENCE", "large": "x" * 40000}})
    db.v2_jobs.insert_one({"run_id": "r", "job_id": "j", "node_id": "done", "state": "SUCCEEDED",
        "output": {"context": "PRIVATE EVIDENCE", "large": "x" * 40000}})
    listed = client.get("/api/v2/tenants/one/runs").json()
    assert "output" not in listed["items"][0]
    detail = client.get("/api/v2/tenants/one/runs/r").json()
    assert "output" not in detail
    assert detail["output_snapshot"]["omitted"]
    job = next(n for n in detail["nodes"] if n["node_id"] == "done")
    assert "output" not in job
    assert job["output_snapshot"]["omitted"]
    assert "PRIVATE EVIDENCE" not in str(detail)
    assert "x" * 40000 not in str(detail)
