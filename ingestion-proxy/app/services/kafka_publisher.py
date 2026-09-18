import json
import logging
import asyncio
from typing import Any

from aiokafka import AIOKafkaProducer

from app.core.config import settings


class KafkaPublisher:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self._trace_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        if self._producer is not None:
            return

        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is None:
            return

        if self._trace_tasks:
            await asyncio.gather(*self._trace_tasks, return_exceptions=True)
        await self._producer.stop()
        self._producer = None

    async def publish_received(self, message: dict[str, Any]) -> None:
        if self._producer is None:
            raise RuntimeError("Kafka producer is not initialized")

        await self._producer.send_and_wait(settings.kafka_received_topic, message)

    async def publish_dead_letter(self, message: dict[str, Any]) -> None:
        if self._producer is None:
            raise RuntimeError("Kafka producer is not initialized")

        await self._producer.send_and_wait(settings.kafka_dead_letter_topic, message)

    async def publish_trace(self, message: dict[str, Any]) -> None:
        """Queue debug telemetry without awaiting a broker acknowledgement."""
        if not settings.debug_trace_enabled:
            return
        if self._producer is None:
            logging.getLogger(__name__).warning(
                "Trace event skipped because Kafka producer is not initialized"
            )
            return
        task = asyncio.create_task(self._send_trace(message))
        self._trace_tasks.add(task)
        task.add_done_callback(self._trace_tasks.discard)

    async def _send_trace(self, message: dict[str, Any]) -> None:
        try:
            assert self._producer is not None
            await self._producer.send_and_wait(settings.kafka_trace_topic, message)
        except Exception:
            logging.getLogger(__name__).exception(
                "Trace event publication failed; continuing ingestion"
            )


kafka_publisher = KafkaPublisher()
