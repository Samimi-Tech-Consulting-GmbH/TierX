import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import mongomock
import pytest
from tierx_workflows import validate_graph
from app.workflows.engine import Engine
from app.workflows.tools import NodeFailure, Tools
from app.workflows.storage import isolated, wrap
from workflow_database import Database, Client


@pytest.mark.asyncio
async def test_scheduler_recovers_expired_leases_and_limits_parallel_nodes(monkeypatch):
    from app.workflows import engine as module

    mongo = mongomock.MongoClient(tz_aware=True)
    raw = Client(mongo)
    mongo.soc_mind_platform.tenants.insert_one(
        {"tenant_id": "t", "db_name": "tenant", "status": "ACTIVE"}
    )
    monkeypatch.setattr(module, "get_client", lambda: raw)
    monkeypatch.setattr(module, "get_database", lambda: raw["soc_mind_platform"])
    engine = Engine()
    engine.tools.schedule = AsyncMock()
    release = asyncio.Event()
    seen = []

    async def execute(db, job):
        seen.append(job["job_id"])
        await release.wait()

    engine.execute = execute
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    for index in range(8):
        mongo.tenant.v2_jobs.insert_one(
            {
                "job_id": str(index),
                "state": "RUNNING" if index == 0 else "PENDING",
                "lease_expires_at": expired,
                "heartbeat_at": expired if index == 0 else None,
                "created_at": expired,
                "routed": False,
            }
        )
    await engine.tick()
    await asyncio.sleep(0)
    assert len(engine.tasks) == 5
    assert len(seen) == 5 and "0" in seen
    assert mongo.tenant.v2_jobs.find_one({"job_id": "0"})["lease_owner"] == engine.owner
    assert mongo.tenant.v2_jobs.count_documents({"state": "PENDING"}) == 3
    release.set()
    await asyncio.gather(*engine.tasks)


@pytest.mark.asyncio
async def test_invalid_fallback_is_not_marked_handled():
    from tierx_workflows.llm import ModelError

    mongo = mongomock.MongoClient(tz_aware=True)
    db = Database(mongo.tenant)
    mongo.tenant.v2_alerts.insert_one({"alert_id": "a"})
    mongo.tenant.v2_jobs.insert_one(
        {"job_id": "failed", "run_id": "r", "state": "FAILED"}
    )
    with pytest.raises(ModelError):
        await Tools().execute(
            db,
            {"run_id": "r", "alert_id": "a"},
            {
                "id": "catch",
                "type": "catch",
                "config": {
                    "replacement": {},
                    "output_schema": {"type": "object", "required": ["evidence"]},
                },
            },
            {"error_input": {"job_id": "failed"}},
        )
    assert "handled_by" not in mongo.tenant.v2_jobs.find_one({"job_id": "failed"})


def parallel_graph():
    nodes = [
        {"id": "entry", "type": "entry", "config": {}},
        {
            "id": "fork",
            "type": "fork",
            "config": {"branches": ["right", "left"], "join_id": "join"},
        },
        {
            "id": "left",
            "type": "decision",
            "config": {"path": "alert.test", "operator": "exists"},
        },
        {
            "id": "right",
            "type": "decision",
            "config": {"path": "alert.test", "operator": "exists"},
        },
        {
            "id": "fallback",
            "type": "catch",
            "config": {"replacement": {"available": False}},
        },
        {"id": "join", "type": "join", "config": {"fork_id": "fork"}},
        {"id": "done", "type": "complete", "config": {}},
    ]
    edges = [
        {"source": "entry", "target": "fork", "sourceHandle": "success"},
        {"source": "fork", "target": "left", "sourceHandle": "left"},
        {"source": "fork", "target": "right", "sourceHandle": "right"},
    ]
    for node in ("left", "right"):
        edges += [
            {"source": node, "target": "join", "sourceHandle": port}
            for port in ("true", "false")
        ]
    edges += [
        {"source": "left", "target": "fallback", "sourceHandle": "error"},
        {"source": "fallback", "target": "join", "sourceHandle": "success"},
        {"source": "join", "target": "done", "sourceHandle": "success"},
    ]
    return {
        "format_version": "1.0",
        "nodes": nodes,
        "edges": [{"id": str(i), **e} for i, e in enumerate(edges)],
    }


@pytest.mark.asyncio
async def test_parallel_catch_join_and_idempotent_dispatch():
    graph = validate_graph(parallel_graph())
    mongo = mongomock.MongoClient(tz_aware=True)
    db = Database(mongo.tenant)
    engine = Engine()
    real = engine.tools.execute

    async def execute(database, run, node, job):
        if node["id"] == "left":
            raise NodeFailure("SYNTHETIC_PROVIDER_FAILURE")
        return await real(database, run, node, job)

    engine.tools.execute = execute
    run = {
        "run_id": "run",
        "alert_id": "alert",
        "tenant_id": "tenant",
        "cohort": "test",
        "graph": graph,
        "input": {},
        "resources": {},
        "state": "PENDING",
        "created_at": datetime.now(timezone.utc),
    }
    mongo.tenant.v2_runs.insert_one(dict(run))
    await engine.initialize(db, run)
    for _ in range(12):
        for record in list(mongo.tenant.v2_jobs.find({"state": "PENDING"})):
            mongo.tenant.v2_jobs.update_one(
                {"job_id": record["job_id"]},
                {"$set": {"state": "RUNNING", "lease_owner": engine.owner}},
            )
            await engine.execute(db, record)
        for record in list(
            mongo.tenant.v2_jobs.find(
                {"state": {"$in": ["SUCCEEDED", "FAILED"]}, "routed": False}
            )
        ):
            await engine.route(db, record)
            await engine.route(db, record)  # replay the durable routing/outbox boundary
    assert mongo.tenant.v2_runs.find_one({})["state"] == "SUCCEEDED_WITH_WARNINGS"
    failed = mongo.tenant.v2_jobs.find_one({"node_id": "left"})
    assert failed["state"] == "FAILED" and failed["handled_by"] == "fallback"
    join = mongo.tenant.v2_jobs.find_one({"node_id": "join"})
    assert list(join["output"]["branches"]) == ["right", "left"]
    assert mongo.tenant.v2_jobs.count_documents({"node_id": "join"}) == 1
    assert mongo.tenant.alerts.count_documents({}) == 0


@pytest.mark.asyncio
async def test_scoped_stage_access_never_writes_v1_or_other_cohort():
    mongo = mongomock.MongoClient(tz_aware=True)
    raw = Client(mongo)
    assert wrap(raw) is raw
    with isolated("tenant", "t", "one"):
        db = wrap(raw)["tenant"]
        await db["alerts"].insert_one({"alert_id": "a"})
        await db["alerts"].update_one(
            {"alert_id": "a"}, {"$set": {"status": "ANALYZING"}}
        )
        with pytest.raises(ValueError):
            wrap(raw)["other_tenant"]
    with isolated("tenant", "t", "two"):
        assert await wrap(raw)["tenant"]["alerts"].find_one({"alert_id": "a"}) is None
    assert mongo.tenant.alerts.count_documents({}) == 0
    assert mongo.tenant.v2_alerts.find_one({})["cohort"] == "one"


@pytest.mark.asyncio
async def test_typed_validation_and_normalization():
    mongo = mongomock.MongoClient(tz_aware=True)
    db = Database(mongo.tenant)
    tools = Tools()
    run = {
        "alert_id": "a",
        "resources": {
            "active_schema": {
                "schema_id": "s",
                "version": 1,
                "critical_fields": ["host.hostname"],
                "field_mapping": {
                    "host.hostname": "result.host",
                    "event.severity": "result.severity",
                },
            }
        },
    }
    mongo.tenant.v2_alerts.insert_one(
        {
            "alert_id": "a",
            "raw_payload": {"result": {"host": "example", "severity": "5"}},
        }
    )
    job = {"ancestors": {}}
    validated, _ = await tools.execute(
        db, run, {"id": "v", "type": "validation", "config": {}}, job
    )
    assert validated["validated"]
    normalized, _ = await tools.execute(
        db, run, {"id": "n", "type": "normalization", "config": {}}, job
    )
    assert normalized["normalized_payload"]["host.hostname"] == "example"
    assert mongo.tenant.alerts.count_documents({}) == 0
