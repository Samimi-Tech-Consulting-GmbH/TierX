import asyncio
from types import SimpleNamespace

import pytest

from tierx_runtime import DEFAULTS, RuntimeSettings, effective, installed, validate
from app.core.config import settings
from app.workers.base import BaseWorker
from unittest.mock import AsyncMock
from app.workers import analysis_worker


@pytest.mark.asyncio
async def test_core_start_failure_cleans_partial_group_and_can_retry():
    from main import start_core_workers
    first = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    second = SimpleNamespace(start=AsyncMock(side_effect=[RuntimeError("startup failed"), None]), stop=AsyncMock())
    pending = []
    with pytest.raises(RuntimeError):
        await start_core_workers([first, second], pending)
    assert pending == []
    first.stop.assert_awaited_once()
    second.stop.assert_awaited_once()
    assert await start_core_workers([first, second], pending) == [first, second]


@pytest.mark.asyncio
async def test_failed_optional_stop_retains_reference():
    from main import stop_optional
    worker = SimpleNamespace(stop=AsyncMock(side_effect=[RuntimeError("shutdown failed"), None]))
    optional = {"analysis": worker}
    with pytest.raises(RuntimeError):
        await stop_optional(optional, "analysis")
    assert optional["analysis"] is worker
    await stop_optional(optional, "analysis")
    assert optional == {}


@pytest.mark.asyncio
async def test_producer_start_failure_closes_both_resources(monkeypatch):
    from app.workers import base
    consumer = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    producer = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError("producer failed")), stop=AsyncMock())
    monkeypatch.setattr(base, "AIOKafkaConsumer", lambda *args, **kwargs: consumer)
    monkeypatch.setattr(base, "AIOKafkaProducer", lambda *args, **kwargs: producer)
    worker = Worker("synthetic", "input", None)
    with pytest.raises(RuntimeError):
        await worker.start()
    consumer.stop.assert_awaited_once()
    producer.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_analysis_drain_waits_for_inflight_claim(monkeypatch):
    worker = analysis_worker.AgenticAnalysisWorker()
    claimed, release = asyncio.Event(), asyncio.Event()
    cursor = SimpleNamespace(to_list=AsyncMock(return_value=[{"db_name": "synthetic"}]))
    monkeypatch.setattr(analysis_worker, "get_database", lambda: {"tenants": SimpleNamespace(find=lambda *args: cursor)})
    monkeypatch.setattr(analysis_worker, "get_client", lambda: {"synthetic": {}})
    monkeypatch.setattr(worker, "_ensure_indexes", AsyncMock())
    async def claim(db):
        claimed.set()
        await release.wait()
        return None
    monkeypatch.setattr(worker, "_claim", claim)
    tick = asyncio.create_task(worker._scheduler_tick())
    await claimed.wait()
    stop = asyncio.create_task(worker.stop())
    await asyncio.sleep(0)
    assert not stop.done()
    release.set()
    await tick
    await stop


def test_environment_precedence_and_empty_override():
    values, locked = effective({"ollama_model": "saved-model"}, {
        "TIERX_OLLAMA_MODEL": "canonical-model", "OLLAMA_MODEL": "legacy-model",
        "TIERX_PUBLIC_URL": ""})
    assert values["ollama_model"] == "canonical-model"
    assert locked == ["ollama_model"]
    assert not installed({"state": "COMPLETING"})


@pytest.mark.asyncio
async def test_job_snapshot_survives_revision_change_and_is_task_local():
    runtime = RuntimeSettings(SimpleNamespace(ollama_model="base"))
    runtime.values = {"ollama_model": "old"}
    started, changed = asyncio.Event(), asyncio.Event()
    async def active():
        with runtime.capture() as snapshot:
            started.set()
            await changed.wait()
            assert runtime.ollama_model == "old"
            assert snapshot == {"ollama_model": "old"}
    task = asyncio.create_task(active())
    await started.wait()
    runtime.values = {"ollama_model": "new"}
    runtime.revision = 2
    assert runtime.ollama_model == "new"
    changed.set()
    await task
    with runtime.capture({"ollama_model": "durable-retry"}):
        assert runtime.ollama_model == "durable-retry"
    assert runtime.ollama_model == "new"


class Worker(BaseWorker):
    async def process(self, data):
        return None


@pytest.mark.asyncio
async def test_drain_does_not_commit_unprocessed_message():
    worker = Worker("synthetic", "input", None)
    worker._draining = True
    class Consumer:
        committed = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            return SimpleNamespace(value={})
        async def commit(self):
            self.committed = True
    consumer = Consumer()
    worker._consumer = consumer
    await worker._run()
    assert not consumer.committed


@pytest.mark.asyncio
async def test_completed_message_commits_after_snapshot_processing(monkeypatch):
    worker = Worker("synthetic", "input", None)
    worker._draining = False
    events = []
    class Consumer:
        sent = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self.sent:
                raise StopAsyncIteration
            self.sent = True
            return SimpleNamespace(value={})
        async def commit(self):
            events.append("committed")
    async def handle(message):
        events.append("processed")
        assert settings.local.get() is not None
    monkeypatch.setattr(worker, "_handle", handle)
    worker._consumer = Consumer()
    await worker._run()
    assert events == ["processed", "committed"]


@pytest.mark.parametrize("values", [{"ollama_url": "https://user:password@example.com"},
                                   {"ollama_url": "https://example.com?token=x"},
                                   {"llm_analysis_enabled": True, "correlation_enabled": False}])
def test_invalid_runtime_settings(values):
    with pytest.raises(ValueError):
        validate(values)


@pytest.mark.asyncio
async def test_analysis_scheduler_persists_and_reuses_snapshot_with_real_run_id(monkeypatch):
    worker = analysis_worker.AgenticAnalysisWorker()
    runs = AsyncMock()
    db = {analysis_worker.RUNS_COLLECTION: runs}
    cursor = SimpleNamespace(to_list=AsyncMock(return_value=[{"db_name": "synthetic-tenant"}]))
    monkeypatch.setattr(analysis_worker, "get_database", lambda: {"tenants": SimpleNamespace(find=lambda *args: cursor)})
    monkeypatch.setattr(analysis_worker, "get_client", lambda: {"synthetic-tenant": db})
    monkeypatch.setattr(worker, "_ensure_indexes", AsyncMock())
    job = {"analysis_run_id": "synthetic-run", "configuration_revision": 1,
           "configuration_snapshot": {"ollama_model": "original-model"}}
    monkeypatch.setattr(worker, "_claim", AsyncMock(side_effect=[job, None]))
    async def execute(database, claimed):
        assert settings.ollama_model == "original-model"
        assert claimed["configuration_revision"] == 1
    monkeypatch.setattr(worker, "_execute", execute)
    await worker._scheduler_tick()
    query, update = runs.update_one.await_args.args
    assert query == {"analysis_run_id": "synthetic-run"}
    assert update["$set"]["configuration_revision"] == 1
    assert update["$set"]["configuration_snapshot"]["ollama_model"] == "original-model"


@pytest.mark.asyncio
async def test_failed_persistence_rewinds_without_committing(monkeypatch):
    worker = Worker("synthetic", "input", None)
    worker._draining = False
    events = []
    class Consumer:
        remaining = 2
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.remaining:
                raise StopAsyncIteration
            self.remaining -= 1
            return SimpleNamespace(value={}, topic="input", partition=0, offset=7)
        def seek(self, partition, offset):
            events.append(("rewound", offset))
        async def commit(self):
            events.append("committed")
    monkeypatch.setattr(worker, "_handle", AsyncMock(side_effect=[RuntimeError("synthetic failure"), None]))
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    worker._consumer = Consumer()
    await worker._run()
    assert events == [("rewound", 7), "committed"]
