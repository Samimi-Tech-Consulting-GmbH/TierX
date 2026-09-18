"""
Base worker that all pipeline stage workers inherit from.

Each worker follows the same contract:
  1. Consume a message from its input Kafka topic.
  2. Process / transform the alert payload.
  3. Optionally read from or write to MongoDB (depends on the stage).
  4. Produce the result to the next Kafka topic (or dead-letter on failure).
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.core.config import settings
from app.services.trace import TraceSpan


class BaseWorker(abc.ABC):

    def __init__(
        self,
        name: str,
        input_topic: str,
        output_topic: str | None,
        consumer_group: str | None = None,
        auto_offset_reset: str = "earliest",
    ):
        self.name = name
        self.input_topic = input_topic
        self.output_topic = output_topic
        self.consumer_group = consumer_group or f"pipeline-{name}"
        self.auto_offset_reset = auto_offset_reset
        self.logger = logging.getLogger(f"worker.{name}")

        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._task: asyncio.Task | None = None
        self._trace_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._consumer = AIOKafkaConsumer(
            self.input_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=self.consumer_group,
            auto_offset_reset=self.auto_offset_reset,
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda value: value.encode("utf-8"),
        )
        await self._consumer.start()
        await self._producer.start()
        self._task = asyncio.create_task(self._run(), name=f"worker-{self.name}")
        self.logger.info("Started  [%s] → [%s]", self.input_topic, self.output_topic)

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()
        if self._trace_tasks:
            await asyncio.gather(*self._trace_tasks, return_exceptions=True)
        if self._producer:
            await self._producer.stop()
        self.logger.info("Stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self):
        assert self._consumer is not None
        try:
            async for msg in self._consumer:
                await self._handle(msg)
        except asyncio.CancelledError:
            raise

    async def _handle(self, msg: Any):
        """Process one Kafka message with dead-letter routing on unexpected failure."""
        try:
            result = await self.process(msg.value)
            if result is not None and self.output_topic:
                await self.produce(self.output_topic, result)
        except Exception:
            self.logger.exception("Unexpected failure — routing to dead-letter")
            await self.produce_dead_letter(
                alert_id=msg.value.get("alert_id", "unknown"),
                tenant_id=msg.value.get("tenant_id"),
                alert_type=msg.value.get("alert_type"),
                source_system=msg.value.get("source_system"),
                raw_payload=msg.value.get("raw_payload"),
                error_type="INTERNAL_ERROR",
                error_detail=f"Unexpected error in {self.name}",
                failed_stage=self.name.upper().replace("-", "_"),
            )

    # ------------------------------------------------------------------
    # Produce helpers
    # ------------------------------------------------------------------

    async def produce(self, topic: str, message: dict[str, Any]):
        assert self._producer is not None
        key = str(message.get("tenant_id") or message.get("alert_id") or "platform")
        await self._producer.send_and_wait(topic, message, key=key)

    async def produce_trace(self, message: dict[str, Any]):
        if not settings.debug_trace_enabled:
            return
        task = asyncio.create_task(self._send_trace(message))
        self._trace_tasks.add(task)
        task.add_done_callback(self._trace_tasks.discard)

    async def _send_trace(self, message: dict[str, Any]):
        try:
            await self.produce(settings.kafka_trace_topic, message)
        except Exception:
            self.logger.exception(
                "Trace event publication failed; continuing alert processing"
            )

    def trace_span(self, stage: str, data: dict[str, Any]) -> TraceSpan:
        return TraceSpan(
            publisher=self.produce_trace,
            stage=stage,
            service=f"pipeline-{self.name}",
            data=data,
        )

    async def produce_dead_letter(
        self,
        *,
        alert_id: str,
        tenant_id: str | None,
        alert_type: str | None,
        source_system: str | None,
        raw_payload: dict[str, Any] | None,
        error_type: str,
        error_detail: str | None = None,
        failed_fields: list[str] | None = None,
        failed_stage: str | None = None,
        extra: dict[str, Any] | None = None,
    ):
        dlq_msg = {
            "alert_id": alert_id,
            "tenant_id": tenant_id,
            "alert_type": alert_type,
            "source_system": source_system,
            "raw_payload": raw_payload,
            "status": "FAILED",
            "kafka_state": "DLQ",
            "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
            "error_type": error_type,
            "error_detail": error_detail,
            "failed_fields": failed_fields or [],
            "failed_stage": failed_stage,
            **(extra or {}),
        }
        await self.produce(settings.kafka_dead_letter_topic, dlq_msg)
        self.logger.warning(
            "Dead-lettered alert_id=%s error_type=%s", alert_id, error_type,
        )

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def process(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """
        Transform a single deserialized message.

        Return a dict payload for the next topic, or None when the worker
        handles its own routing (e.g. validation may route to DLQ directly).
        """
        ...
