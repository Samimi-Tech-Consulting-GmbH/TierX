"""Populate the running disposable acceptance stack with an explorable demo.

Only localhost is supported. Credentials and generated entry tokens remain in
the acceptance harness's private state file, never in this repository.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import secrets
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]
STATE = Path.home() / ".local/share/tierx-workflow-sandbox"


def main():
    path = STATE / "credentials.json"
    saved = json.loads(path.read_text())
    if saved["target"] != "http://127.0.0.1:18084":
        raise RuntimeError("This demo only supports the isolated localhost acceptance stack")
    client = httpx.Client(base_url=saved["target"], timeout=30, trust_env=False)
    login = client.post("/api/v1/auth/login", json={key: saved[key] for key in ("email", "password")})
    login.raise_for_status()
    client.headers["Authorization"] = "Bearer " + login.json()["access_token"]

    def api(url, method="GET", body=None):
        response = client.request(method, url, json=body)
        response.raise_for_status()
        return response.json()

    tenant = saved["tenant_id"]
    api(f"/api/v1/admin/tenants/{tenant}", "PUT", {"display_name": "TierX Demo — ready to test"})
    definitions = api("/api/v2/admin/workflow-definitions")["items"]
    source_code = saved.get("acceptance_workflow_code") or next(row["code"] for row in definitions
        if row["kind"] == "workflow" and row["code"].startswith("sandbox-") and tenant in row["tenant_ids"])
    saved["acceptance_workflow_code"] = source_code
    source = next(row for row in definitions if row["code"] == source_code)
    selector = next(node for node in source["configuration"]["nodes"] if node["type"] == "playbook_selector")
    original_pb = next(row for row in definitions if row["code"] == selector["config"]["fallback"])
    original_agent_code = next(node["config"]["definition_code"] for node in original_pb["configuration"]["nodes"] if node["type"] == "agent")
    original_agent = next(row for row in definitions if row["code"] == original_agent_code)

    changed = False
    def publish(kind, code, name, description, configuration):
        nonlocal changed
        old = next((row for row in definitions if row["kind"] == kind and row["code"] == code), {})
        if not changed and old.get("active_revision") and all(old.get(key) == value for key, value in {
            "name": name, "description": description, "tenant_ids": [tenant], "configuration": configuration}.items()):
            return
        api(f"/api/v2/admin/workflow-definitions/{kind}/{code}", "PUT", {
            "name": name, "description": description, "tenant_ids": [tenant],
            "configuration": configuration, "expected_version": old.get("draft_version", 0)})
        api(f"/api/v2/admin/workflow-definitions/{kind}/{code}/publish", "POST")
        changed = True

    def layout(graph):
        for index, node in enumerate(graph["nodes"]):
            node["label"] = node["id"].replace("_", " ").title()
            node["position"] = {"x": (index % 3) * 280, "y": (index // 3) * 180}
        return graph

    publish("agent", "demo-asset-investigator", "Demo · Asset investigator (protocol fixture)",
        "Fast synthetic reasoning fixture calling a real approved MCP asset-context tool. Not a real model.", original_agent["configuration"])
    real = deepcopy(original_pb["configuration"])
    next(node for node in real["nodes"] if node["type"] == "agent")["config"]["definition_code"] = "demo-asset-investigator"
    publish("playbook", "demo-real-analysis", "Demo · Real phi3 investigation", "MCP asset evidence → deterministic KB → real phi3 → persist analysis. CPU inference can take 3–5 minutes. Jira notification skips when there is no Jira origin.", layout(real))
    quick = deepcopy(real)
    quick["nodes"] = [node for node in quick["nodes"] if node["id"] not in {"analysis", "notify"}]
    next(node for node in quick["nodes"] if node["type"] == "persist_analysis")["config"]["input_path"] = "nodes.agent.output"
    next(node for node in quick["nodes"] if node["type"] == "complete")["config"]["output_path"] = "nodes.agent.output.result"
    quick["edges"] = [{"id": str(i), "source": a["id"], "target": b["id"]} for i, (a, b) in enumerate(zip(quick["nodes"], quick["nodes"][1:]))]
    publish("playbook", "demo-fast-investigation", "Demo · Fast tool + KB investigation", "Seconds, not minutes: synthetic agent protocol, real MCP HTTP tool, real deterministic KB, persisted fixture result. No real LLM inference.", layout(quick))
    entries = saved.setdefault("demo_workflows", {})
    for code, name, book in [("demo-fast-triage", "Demo · 1. Fast triage — start here", "demo-fast-investigation"), ("demo-real-triage", "Demo · 2. Real phi3 triage", "demo-real-analysis")]:
        graph = deepcopy(source["configuration"])
        config = next(node["config"] for node in graph["nodes"] if node["type"] == "playbook_selector")
        config.update(fallback=book, mappings={"sandbox.synthetic": book})
        publish("workflow", code, name, "Raw Splunk-shaped JSON → validation → mapping → dedup → correlation → selected playbook. Fixed per-tenant entry URL.", layout(graph))
        if code not in entries:
            entries[code] = api(f"/api/v2/admin/workflow-definitions/workflow/{code}/entry-credentials", "POST", {"tenant_id": tenant})
    saved.update(workflow_code="demo-fast-triage", ingestion_path=entries["demo-fast-triage"]["path"], entry_token=entries["demo-fast-triage"]["token"])
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600), "w") as handle:
        json.dump(saved, handle, indent=2)

    # Upload through the API; invoke the real deterministic processor on this
    # dedicated local database, without enabling or modifying shared services.
    prefix = f"/api/v1/tenants/{tenant}/knowledge-base"
    documents = api(prefix + "/documents")["items"]
    text = "# Synthetic demo environment\n\n## Asset context\nDB01 is a synthetic database host. svc_backup is a synthetic service account.\n\n## Documentation network\n192.0.2.0/24 is the demo network. IP 192.0.2.10 belongs to the demo host DB01. This is test evidence, not an allowlist.\n\n## Investigation\nPowerShell activity requires review of process context and authorized maintenance. Do not infer a benign verdict from a service-account name alone.\n"
    if not any(row["original_filename"] == "demo-environment.md" for row in documents):
        response = client.post(prefix + "/documents", files={"file": ("demo-environment.md", text.encode(), "text/markdown")})
        response.raise_for_status()
    os.environ["MONGO_URL"] = "mongodb://127.0.0.1:27028/"
    os.environ.setdefault("JWT_SECRET_KEY", secrets.token_hex(32))
    sys.path.insert(0, str(ROOT / "backend"))
    from app.db.mongodb import DatabaseManager
    from app.services.knowledge_base_service import KnowledgeBaseService
    DatabaseManager.initialize()
    record = api(f"/api/v1/admin/tenants/{tenant}")
    db = DatabaseManager.get_tenant_database(record["db_name"])
    while document := KnowledgeBaseService.claim_next(db):
        KnowledgeBaseService.process_claimed(db, document)

    if not saved.get("demo_run_ids"):
        entry = entries["demo-fast-triage"]
        payload = {"result": {"host": "DB01", "src": "192.0.2.10", "user": "svc_backup", "severity": "4", "_time": datetime.now(timezone.utc).isoformat()}}
        payloads = [payload, {"result": {**payload["result"], "_time": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()}},
            {"result": {"host": "UNRELATED-DEMO", "src": "198.51.100.88", "user": "demo.user", "severity": "3", "_time": datetime.now(timezone.utc).isoformat()}}, payload,
            {"result": {"_time": datetime.now(timezone.utc).isoformat()}}]
        runs = []
        for payload in payloads:
            response = client.post(entry["path"], json=payload, headers={"Authorization": "Bearer " + entry["token"]})
            response.raise_for_status()
            runs.append(response.json()["run_id"])
            time.sleep(1)
        saved["demo_run_ids"] = runs
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600), "w") as handle:
            json.dump(saved, handle, indent=2)
    print(json.dumps({"tenant_id": tenant, "workflow_codes": list(entries), "demo_run_ids": saved["demo_run_ids"]}))


if __name__ == "__main__":
    main()
