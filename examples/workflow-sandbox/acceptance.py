"""Disposable localhost acceptance stack; never touches a remote deployment.

Requires dedicated MongoDB on 127.0.0.1:27028 and Ollama on 127.0.0.1:11438.
Run with the application Python dependencies installed. --serve keeps the local
backend, worker and sender alive after checks; Ctrl-C stops only these children.
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
STATE = Path.home() / ".local/share/tierx-workflow-sandbox"


def local_environment():
    """Never let a deployment shell redirect the disposable acceptance stack."""
    return {**{key: value for key, value in os.environ.items()
               if not key.startswith(("TIERX_", "SOC_MIND_"))},
            "MONGO_URL": "mongodb://127.0.0.1:27028/",
            "TIERX_MONGO_URL": "mongodb://127.0.0.1:27028/"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    credentials = STATE / "credentials.json"
    saved = json.loads(credentials.read_text()) if credentials.exists() else {"email": "sandbox-admin@example.com", "password": secrets.token_urlsafe(24)}
    saved.setdefault("encryption_key", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    def save_credentials():
        with os.fdopen(os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
            json.dump({key:value for key,value in saved.items() if key!="access_token"},handle,indent=2)
    save_credentials()
    env = {**local_environment(), "JWT_SECRET_KEY": secrets.token_hex(32),
        "PLATFORM_ADMIN_EMAIL": saved["email"], "PLATFORM_ADMIN_PASSWORD": saved["password"],
        "TIERX_OLLAMA_URL": "http://127.0.0.1:11438", "TIERX_OLLAMA_MODEL": "phi3:latest",
        "WEBHOOK_SECRET_ENCRYPTION_KEY": saved["encryption_key"],
        "TIERX_APP_RELEASE_VERSION": "development", "TIERX_APP_RELEASE_SHA": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "CORS_ORIGINS": "http://127.0.0.1:13004", "EXAMPLE_PROVIDER_TOKEN": secrets.token_urlsafe(24),
        "EXAMPLE_DB": str(STATE / ("provider-" + uuid4().hex + ".sqlite")),
        "TIERX_V2_LOCAL_CONNECTOR_ORIGINS": "http://127.0.0.1:18096"}
    children, logs = [], []
    def start(command, cwd, extra=None):
        log = open(STATE / f"process-{len(children)}.log", "w")
        logs.append(log)
        child = subprocess.Popen(command, cwd=cwd, env={**env, **(extra or {})}, stdout=log, stderr=subprocess.STDOUT)
        children.append(child)
        return child
    client = httpx.Client(base_url="http://127.0.0.1:18084", timeout=310, trust_env=False)
    def api(path, method="GET", body=None, token=None):
        bearer = token or saved.get("access_token", "")
        response = client.request(method, path, json=body, headers={"Authorization": "Bearer " + bearer} if bearer else {})
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:500]}")
        return response.json()
    def node(identity, kind, **config): return {"id": identity, "type": kind, "config": config}
    def graph(nodes, subflow=False):
        return {"format_version": "2.0", "input_capabilities": ["normalization" if subflow else "raw"], "nodes": nodes,
            "edges": [{"id": str(index), "source": left["id"], "target": right["id"]} for index, (left, right) in enumerate(zip(nodes, nodes[1:]))]}
    try:
        start([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "18084"], ROOT / "backend")
        for _ in range(90):
            try:
                if client.get("/api/v1/health").status_code == 200: break
            except httpx.HTTPError: pass
            time.sleep(1)
        else: raise RuntimeError("Backend did not become ready; inspect private process logs")
        saved["access_token"] = api("/api/v1/auth/login", "POST", {"email": saved["email"], "password": saved["password"]})["access_token"]
        tenant = api("/api/v1/admin/tenants", "POST", {"name": "sandbox-" + uuid4().hex[:8], "display_name": "Disposable Workflow Sandbox", "allowed_source_systems": ["SPLUNK"]})
        tenant_id = tenant["tenant_id"]
        api(f"/api/v1/admin/tenants/{tenant_id}/status", "PATCH", {"status": "ACTIVE"})
        # Separate synthetic protocol provider: actual HTTP tools, no real target actions.
        start([sys.executable, "-c", "import server; server.ThreadingHTTPServer(('127.0.0.1',18096),server.Handler).serve_forever()"], ROOT / "examples/workflow-providers")
        start([sys.executable, "workflow_main.py"], ROOT / "pipeline")
        suffix = uuid4().hex[:8]
        profile, synthetic, connector, agent, playbook, workflow = [name + "-" + suffix for name in ["real-model", "protocol", "assets", "specialist", "triage", "sandbox"]]
        for code, body in [(profile, {"provider":"ollama","base_url":"http://127.0.0.1:11438","model":"phi3:latest","tool_mode":"disabled","max_tokens":192,"timeout_seconds":300}),
            (synthetic, {"provider":"openai_compatible","base_url":"http://127.0.0.1:18096/v1","model":"synthetic-protocol-fixture","tool_mode":"native","api_key":env["EXAMPLE_PROVIDER_TOKEN"]})]:
            api("/api/v2/admin/llm-profiles/" + code, "PUT", {**body, "profile_code":code,"tenant_ids":[tenant_id]})
            print("Preflight:", code, flush=True)
            api("/api/v2/admin/llm-profiles/" + code + "/test", "POST")
        spec = importlib.util.spec_from_file_location("provider_schema", ROOT / "examples/workflow-providers/server.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        api("/api/v2/admin/connectors/" + connector, "PUT", {"name":"Synthetic assets", "kind":"mcp", "url":"http://127.0.0.1:18096/mcp", "tenant_ids":[tenant_id],"credential":env["EXAMPLE_PROVIDER_TOKEN"],
            "tools":[{"name":"asset_context","description":"Synthetic asset facts","input_schema":module.INPUT,"output_schema":module.OUTPUT,"retry_safe":True}]})
        schema = {"type":"object","properties":{"headline":{"type":"string"},"confidence":{"enum":["HIGH","MEDIUM","LOW"]}},"required":["headline","confidence"],"additionalProperties":False}
        def publish(kind, code, config):
            api(f"/api/v2/admin/workflow-definitions/{kind}/{code}", "PUT", {"name":code,"tenant_ids":[tenant_id],"configuration":config})
            return api(f"/api/v2/admin/workflow-definitions/{kind}/{code}/publish", "POST")
        publish("agent", agent, {"profile_code":synthetic,"prompt":"Use the approved tool and return evidence.","tools":[f"connector:{connector}:asset_context"],"output_schema":{"type":"object","properties":{"headline":{"type":"string"}},"required":["headline"],"additionalProperties":False}})
        publish("playbook", playbook, graph([node("entry","entry"),node("agent","agent",definition_code=agent),node("knowledge","kb_deterministic",top_k=5),
            node("analysis","llm_analysis",profile_code=profile,prompt="Summarize the supplied synthetic alert and upstream evidence. Be brief and do not invent facts.",output_schema=schema),
            node("persist","persist_analysis",input_path="nodes.analysis.output"),node("notify","notify_jira"),node("done","complete",output_path="nodes.analysis.output.result")],True))
        mapping = {"host.name":"result.host","source.ip":"result.src","user.name":"result.user","event.created":"result._time","event.severity":"result.severity"}
        publish("workflow",workflow,graph([node("entry","entry",input_mode="raw",source_system="SPLUNK",alert_type="sandbox.synthetic",timestamp_path="result._time"),
            node("validation","validation",field_mapping=mapping,critical_fields=["host.name"]),node("mapping","normalization",field_mapping=mapping),
            node("dedup","fingerprint",fields=["host.name","event.created"]),node("correlation","correlation",group=None),
            node("select","playbook_selector",mode="static",fallback=playbook),node("done","complete",output_path="nodes.select.output.result")]))
        entry = api(f"/api/v2/admin/workflow-definitions/workflow/{workflow}/entry-credentials", "POST", {"tenant_id":tenant_id})
        saved.update(tenant_id=tenant_id,workflow_code=workflow,ingestion_path=entry["path"],entry_token=entry["token"],target="http://127.0.0.1:18084")
        save_credentials()
        def submit(payload):
            return api(entry["path"], "POST", payload, entry["token"])
        def follow(accepted, expected):
            for _ in range(240):
                detail=api(f"/api/v2/tenants/{tenant_id}/runs/{accepted['run_id']}")
                if detail["state"] not in {"PENDING","RUNNING"}:
                    assert detail["state"]==expected, detail.get("error",detail["state"])
                    assert detail["workflow_version"]["definition_ref"].startswith("workflow:"+workflow+"@")
                    return detail
                time.sleep(2)
            raise RuntimeError("Workflow did not finish within eight minutes")
        payload={"result":{"host":"DB01","src":"192.0.2.10","user":"svc_backup","severity":"4","_time":datetime.now(timezone.utc).isoformat()}}
        accepted=submit(payload);print("Watching real-model workflow:",accepted["run_id"],flush=True)
        first=follow(accepted,"SUCCEEDED")
        assert first["alert"]["alert_analysis"]["headline"]
        assert all(node.get("input_snapshot") for node in first["nodes"] if node["state"]=="SUCCEEDED")
        duplicate=follow(submit(payload),"FAILED");assert duplicate["error"]["type"]=="DUPLICATED_ALERT"
        invalid=follow(submit({"result":{"_time":datetime.now(timezone.utc).isoformat()}}),"FAILED")
        assert invalid["error"]["type"]=="MISSING_REQUIRED_FIELD"
        related=follow(submit({"result":{**payload["result"],"_time":(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()}}),"SUCCEEDED")
        assert related["alert"]["cluster_id"]==first["alert"]["cluster_id"]
        assert related["alert"]["clustering_status"]=="CORRELATED"
        assert api(f"/api/v2/tenants/{tenant_id}/runs/{first['run_id']}")["alert"]["alert_analysis"]["analysis_id"]==first["alert"]["alert_analysis"]["analysis_id"]
        report={"status":"PASS","tenant_id":tenant_id,"workflow":workflow,"run_id":first["run_id"],"related_run_id":related["run_id"],"duplicate_run_id":duplicate["run_id"],"invalid_run_id":invalid["run_id"],"flow_version":first["workflow_version"],"real_model":"phi3:latest"}
        (STATE/"report.json").write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
        if args.serve:
            start(["node","server.mjs"],ROOT/"examples/workflow-sandbox",{"TIERX_TARGET":saved["target"],"TIERX_UI_ORIGIN":"http://127.0.0.1:13004"})
            print("Sandbox: http://127.0.0.1:4174 ; copy-once local credentials: " + str(credentials),flush=True)
            while True: time.sleep(10)
    finally:
        for child in reversed(children): child.terminate()
        for child in children:
            try: child.wait(timeout=15)
            except subprocess.TimeoutExpired: child.kill()
        for log in logs: log.close()
        client.close()


if __name__=="__main__":main()
