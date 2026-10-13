import json
from unittest.mock import AsyncMock

import httpx
import mongomock
import pytest
from tierx_workflows import GraphError, decide, default_graph, validate_graph
from tierx_workflows.llm import ModelError, infer
from tierx_workflows.safety import sanitize
from app.workflows.tools import NodeFailure, Tools
from workflow_database import Database

READY = {
    "type": "object",
    "properties": {"ready": {"type": "boolean"}},
    "required": ["ready"],
    "additionalProperties": False,
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,native",
    [
        ("ollama", False),
        ("ollama", True),
        ("openai_compatible", False),
        ("openai_compatible", True),
    ],
)
async def test_explicit_provider_protocols_and_key_not_in_body(
    monkeypatch, provider, native
):
    captured = []

    def handle(request):
        captured.append(request)
        call = {
            "id": "call-one",
            "function": {
                "name": "tool_0",
                "arguments": {} if provider == "ollama" else "{}",
            },
        }
        message = (
            {"role": "assistant", "tool_calls": [call]}
            if native
            else {"role": "assistant", "content": '{"ready":true}'}
        )
        body = (
            {"message": message}
            if provider == "ollama" and native
            else (
                {"response": '{"ready":true}'}
                if provider == "ollama"
                else {"choices": [{"message": message}]}
            )
        )
        return httpx.Response(200, json=body)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    profile = {
        "provider": provider,
        "base_url": "https://inference.example",
        "model": "test-model",
    }
    result = await infer(
        profile,
        [{"role": "user", "content": "Synthetic evidence"}],
        api_key="synthetic-test-key",
        schema=None if native else READY,
        tools=[{"type": "function"}] if native else None,
    )
    assert result["kind"] == ("tool_calls" if native else "final")
    assert b"synthetic-test-key" not in captured[0].content
    assert captured[0].headers["authorization"] == "Bearer synthetic-test-key"
    if provider == "ollama":
        assert captured[0].url.path == ("/api/chat" if native else "/api/generate")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,content",
    [
        (500, {"error": "private-provider-detail"}),
        (200, {"response": "not JSON"}),
        (200, {"response": '{"unexpected":true}'}),
    ],
)
async def test_invalid_model_output_fails_closed(monkeypatch, status, content):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, json=content)
            )
        ),
    )
    with pytest.raises(ModelError) as exc:
        await infer(
            {"provider": "ollama", "base_url": "http://ollama", "model": "test"},
            [],
            schema=READY,
        )
    assert "private-provider-detail" not in str(exc.value)


@pytest.mark.asyncio
async def test_emulated_calls_are_persisted_and_replayed_without_model_or_tool_repetition(
    monkeypatch,
):
    db = Database(mongomock.MongoClient(tz_aware=True).tenant)
    tools = Tools()
    mock = AsyncMock(
        side_effect=[
            {
                "result": {
                    "kind": "tool_calls",
                    "calls": [{"name": "tool_0", "arguments": {}}],
                }
            },
            {"result": {"kind": "final", "result": {"ready": True}}},
        ]
    )
    monkeypatch.setattr("app.workflows.tools.infer", mock)
    arguments = (
        db,
        {},
        {"job_id": "node-call"},
        {
            "alert_id": "a",
            "normalized_payload": {
                "host.hostname": "example",
                "api_key": "must-not-leave",
            },
            "raw_payload": {"private": "raw-must-not-leave"},
        },
        {"tools": ["alert_evidence"], "max_rounds": 5, "max_calls": 10},
        {"tool_mode": "json_emulated"},
        None,
        [],
        READY,
    )
    first = await tools.tool_loop(*arguments)
    second = await tools.tool_loop(*arguments)
    assert first == second and mock.await_count == 2
    assert db.raw.v2_tool_calls.count_documents({}) == 1
    assert "must-not-leave" not in str(list(db.raw.v2_tool_calls.find({})))
    assert "raw-must-not-leave" not in str(mock.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        {"name": "shell", "arguments": {}},
        {"name": "tool_0", "arguments": {"url": "https://unapproved.example"}},
    ],
)
async def test_unapproved_calls_cannot_execute(monkeypatch, call):
    db = Database(mongomock.MongoClient().tenant)
    monkeypatch.setattr(
        "app.workflows.tools.infer",
        AsyncMock(return_value={"result": {"kind": "tool_calls", "calls": [call]}}),
    )
    with pytest.raises(NodeFailure, match="UNAUTHORIZED_TOOL_ARGUMENTS"):
        await Tools().tool_loop(
            db,
            {},
            {"job_id": "call"},
            {},
            {"tools": ["alert_evidence"]},
            {"tool_mode": "json_emulated"},
            None,
            [],
            READY,
        )
    assert db.raw.v2_tool_calls.count_documents({}) == 0


def test_flat_ecs_cidr_and_known_credential_redaction():
    assert decide(
        {"alert": {"normalized_payload": {"source.ip": "10.20.30.40"}}},
        {
            "path": "alert.normalized_payload.source.ip",
            "operator": "cidr_contains",
            "value": "10.0.0.0/8",
        },
    )
    assert not decide(
        {"values": [1]}, {"path": "values", "operator": "contains", "value": True}
    )
    value = sanitize(
        {
            "api_key": "secret",
            "credentials": {"password": "secret"},
            "url": "https://example.com/?access_token=secret",
        }
    )
    assert "secret" not in json.dumps(value)


def test_resource_query_injection_and_remote_schema_refs_rejected():
    graph = default_graph()
    graph["nodes"][7]["config"]["profile_code"] = {"$ne": None}
    with pytest.raises(GraphError):
        validate_graph(graph)
    graph = default_graph()
    graph["nodes"][7]["config"]["output_schema"] = {
        "$ref": "https://unapproved.example/schema"
    }
    with pytest.raises(GraphError):
        validate_graph(graph)
