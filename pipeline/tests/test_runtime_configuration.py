import asyncio
from types import SimpleNamespace

import pytest

from tierx_runtime import DEFAULTS, RuntimeSettings, effective, installed, validate
from app.core.config import settings
from app.workers.base import BaseWorker
from unittest.mock import AsyncMock
from app.workers import analysis_worker


@pytest.mark.asyncio
async def test_malformed_kafka_payload_is_quarantined_without_stopping_worker(monkeypatch):
    worker = Worker("synthetic", "input", None)
    worker._draining = False
    remaining = iter([b"not-json", b"[]", b'{"alert_id":"synthetic"}'])
    class Consumer:
        committed = 0
        def __aiter__(self): return self
        async def __anext__(self):
            try: value = next(remaining)
            except StopIteration: raise StopAsyncIteration
            return SimpleNamespace(value=value, topic="input", partition=0, offset=self.committed)
        async def commit(self): self.committed += 1
    worker._consumer = Consumer()
    dead_letter = AsyncMock()
    process = AsyncMock(return_value=None)
    monkeypatch.setattr(worker, "produce_dead_letter", dead_letter)
    monkeypatch.setattr(worker, "process", process)
    await worker._run()
    assert worker._consumer.committed == 3
    assert dead_letter.await_count == 2
    process.assert_awaited_once_with({"alert_id": "synthetic"})
    assert all(call.kwargs["raw_payload"] is None for call in dead_letter.await_args_list)


@pytest.mark.asyncio
async def test_malformed_terminal_records_never_recursively_publish(monkeypatch):
    from app.workers.trace_worker import TraceWorker
    from app.workers.dead_letter_worker import DeadLetterWorker
    record = SimpleNamespace(value=b"opaque-invalid-data", topic="terminal", partition=0, offset=1)
    dlq = DeadLetterWorker()
    persist = AsyncMock()
    monkeypatch.setattr(dlq, "process", persist)
    monkeypatch.setattr(dlq, "produce_dead_letter", AsyncMock(side_effect=AssertionError("recursive DLQ")))
    await dlq._handle_malformed(record)
    assert persist.await_args.args[0]["error_type"] == "INVALID_KAFKA_MESSAGE"
    trace = TraceWorker()
    monkeypatch.setattr(trace, "produce_dead_letter", AsyncMock(side_effect=AssertionError("recursive trace")))
    await trace._handle_malformed(record)


@pytest.mark.parametrize("worker_type", ["trace", "dead-letter"])
@pytest.mark.asyncio
async def test_terminal_persistence_failures_propagate_for_replay(monkeypatch, worker_type):
    from app.workers.trace_worker import TraceWorker
    from app.workers.dead_letter_worker import DeadLetterWorker
    worker = TraceWorker() if worker_type == "trace" else DeadLetterWorker()
    monkeypatch.setattr(worker, "process", AsyncMock(side_effect=RuntimeError("database unavailable")))
    with pytest.raises(RuntimeError):
        await worker._handle(SimpleNamespace(value={}))


def test_empty_environment_aliases_use_shared_precedence():
    from tierx_runtime import normalize_environment
    env = {"TIERX_MONGO_URL": "", "MONGO_URL": "", "SOC_MIND_MONGO_URL": "legacy"}
    normalize_environment(env)
    assert env["MONGO_URL"] == "legacy"
    env["TIERX_MONGO_URL"] = "canonical"
    normalize_environment(env)
    assert env["MONGO_URL"] == "canonical"


@pytest.mark.asyncio
async def test_correlation_drains_only_current_scheduler_item(monkeypatch):
    from app.workers import correlation_worker as module
    worker = module.CorrelationClusteringWorker()
    tenants = SimpleNamespace(to_list=AsyncMock(return_value=[{"db_name": "synthetic"}]))
    clusters = SimpleNamespace(find=lambda *args: SimpleNamespace(to_list=AsyncMock(return_value=[
        {"pending_analysis_request": {"cluster_id": "first"}},
        {"pending_analysis_request": {"cluster_id": "second"}},
    ])))
    monkeypatch.setattr(module, "get_database", lambda: {"tenants": SimpleNamespace(find=lambda *args: tenants)})
    monkeypatch.setattr(module, "get_client", lambda: {"synthetic": {module.CLUSTERS_COLLECTION: clusters, module.ALERTS_COLLECTION: {}}})
    monkeypatch.setattr(worker, "_ensure_indexes", AsyncMock())
    seen = []
    async def publish(db, message):
        seen.append(message["cluster_id"])
        worker._draining = True
    monkeypatch.setattr(worker, "_publish_request", publish)
    await worker._scheduler_tick()
    assert seen == ["first"]


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


@pytest.mark.parametrize("url", ["http://olla ma:11434", "https://exa mple.com", "http://169.254.169.254",
                                "http://[fe80::1]", "http://[::ffff:169.254.169.254]", "http://0.0.0.0", "http://224.0.0.1"])
def test_invalid_ollama_authorities(url):
    with pytest.raises(ValueError):
        validate({"ollama_url": url})


def analysis_request():
    return {"alert_id": "synthetic-alert", "tenant_id": "synthetic-tenant", "cluster_id": "synthetic-cluster",
            "analysis_type": "CLUSTER_ANALYSIS", "debounce_outcome": "IMMEDIATE",
            "requested_analysis_version": 1, "trigger_reason": "MEMBERSHIP_CHANGED", "is_final": False}


@pytest.mark.parametrize("bad_record", [{"opaque": "never-copy-to-dlq"}, analysis_request()])
@pytest.mark.asyncio
async def test_poison_analysis_record_dead_letters_and_partition_advances(monkeypatch, bad_record):
    worker = analysis_worker.AgenticAnalysisWorker()
    worker._draining = False
    valid = analysis_request()
    records = iter([bad_record, valid])
    class Consumer:
        committed = 0
        def __aiter__(self): return self
        async def __anext__(self):
            try: data = next(records)
            except StopIteration: raise StopAsyncIteration
            return SimpleNamespace(value=data, topic="clustered", partition=0, offset=self.committed)
        async def commit(self): self.committed += 1
        def seek(self, *args): raise AssertionError("Poison input must not rewind")
    worker._consumer = Consumer()
    monkeypatch.setattr(worker, "_tenant", AsyncMock(side_effect=[analysis_worker.InactiveAnalysisTenantError("inactive"), {"db_name": "synthetic"}]
        if "cluster_id" in bad_record else [{"db_name": "synthetic"}]))
    monkeypatch.setattr(worker, "_ensure_indexes", AsyncMock())
    runs = AsyncMock()
    monkeypatch.setattr(analysis_worker, "get_client", lambda: {"synthetic": {analysis_worker.RUNS_COLLECTION: runs}})
    dead_letter = AsyncMock()
    monkeypatch.setattr(worker, "produce_dead_letter", dead_letter)
    await worker._run()
    assert worker._consumer.committed == 2
    runs.update_one.assert_awaited_once()
    dead_letter.assert_awaited_once()
    assert dead_letter.await_args.kwargs["error_type"] == "INVALID_ANALYSIS_REQUEST"
    assert dead_letter.await_args.kwargs["raw_payload"] is None
    assert "never-copy-to-dlq" not in str(dead_letter.await_args)


@pytest.mark.asyncio
async def test_analysis_storage_and_dlq_failures_remain_retryable(monkeypatch):
    worker = analysis_worker.AgenticAnalysisWorker()
    monkeypatch.setattr(worker, "process", AsyncMock(side_effect=RuntimeError("database unavailable")))
    with pytest.raises(RuntimeError):
        await worker._handle(SimpleNamespace(value=analysis_request()))
    monkeypatch.setattr(worker, "process", AsyncMock(side_effect=analysis_worker.InactiveAnalysisTenantError("inactive")))
    monkeypatch.setattr(worker, "produce_dead_letter", AsyncMock(side_effect=RuntimeError("Kafka unavailable")))
    with pytest.raises(RuntimeError):
        await worker._handle(SimpleNamespace(value=analysis_request()))


@pytest.mark.asyncio
async def test_dead_letter_replay_is_idempotent_per_kafka_delivery(monkeypatch):
    from app.workers.dead_letter_worker import DeadLetterWorker
    worker = DeadLetterWorker()
    documents = {}
    from bson import ObjectId
    async def update_one(query, update, **kwargs):
        documents.setdefault(query["_id"], update["$setOnInsert"])
    collection = SimpleNamespace(update_one=update_one)
    class Database:
        name = "synthetic"
        def __getitem__(self, key): return collection
    monkeypatch.setattr(worker, "_resolve_db", AsyncMock(return_value=Database()))
    data = {"alert_id": "synthetic", "error_type": "TEST", "tenant_id": None}
    record = SimpleNamespace(value=data, topic="dlq", partition=0, offset=4)
    await worker._handle(record)
    await worker._handle(record)
    assert len(documents) == 1
    assert all(isinstance(identity, ObjectId) for identity in documents)
    record.offset = 5
    await worker._handle(record)
    assert len(documents) == 2  # Distinct failures for one alert remain auditable.
    malformed = SimpleNamespace(value=b"invalid", topic="dlq", partition=0, offset=6)
    await worker._handle_malformed(malformed)
    await worker._handle_malformed(malformed)
    assert len(documents) == 3


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
    runs.update_one.assert_not_awaited()  # Snapshot is already part of the atomic claim.


@pytest.mark.asyncio
async def test_analysis_claim_atomically_captures_initial_configuration():
    worker = analysis_worker.AgenticAnalysisWorker()
    runs = AsyncMock()
    await worker._claim({analysis_worker.RUNS_COLLECTION: runs})
    query, update = runs.find_one_and_update.await_args.args
    state = update[0]["$set"]
    assert state["state"] == "RUNNING"
    assert state["configuration_snapshot"]["$ifNull"][0] == "$configuration_snapshot"
    assert state["configuration_snapshot"]["$ifNull"][1]["$literal"] == settings.values
    assert state["configuration_revision"]["$ifNull"] == ["$configuration_revision", settings.revision]


@pytest.mark.parametrize("worker_type", ["trace", "dead-letter"])
@pytest.mark.asyncio
async def test_terminal_workers_rewind_failed_storage_then_commit(monkeypatch, worker_type):
    from app.workers.trace_worker import TraceWorker
    from app.workers.dead_letter_worker import DeadLetterWorker
    worker = TraceWorker() if worker_type == "trace" else DeadLetterWorker()
    worker._draining = False
    events = []
    class Consumer:
        remaining = 2
        def __aiter__(self): return self
        async def __anext__(self):
            if not self.remaining: raise StopAsyncIteration
            self.remaining -= 1
            return SimpleNamespace(value={}, topic="terminal", partition=0, offset=1)
        def seek(self, partition, offset): events.append("rewound")
        async def commit(self): events.append("committed")
    worker._consumer = Consumer()
    monkeypatch.setattr(worker, "process", AsyncMock(side_effect=[RuntimeError("database unavailable"), None]))
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    await worker._run()
    assert events == ["rewound", "committed"]


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
