from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pymongo import ASCENDING, ReturnDocument

from app.core.config import settings
from app.db.mongodb import get_client, get_database

TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "SKIPPED"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def deterministic_id(kind: str, *parts: object) -> str:
    # Persisted identity namespace: changing it would repeat external deliveries.
    identity = ":".join(["soc-mind", "enrichment-action", "v1", kind, *map(str, parts)])
    return str(uuid5(NAMESPACE_URL, identity))


async def validate_public_https_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("ACTION_DESTINATION_REJECTED")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parts.hostname,
            parts.port or 443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("ACTION_DNS_FAILURE") from exc
    resolved = {entry[4][0].split("%", 1)[0] for entry in addresses}
    if not resolved or any(not ipaddress.ip_address(addr).is_global for addr in resolved):
        raise ValueError("ACTION_DESTINATION_REJECTED")
    return url


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decrypt_action_secret(record: dict[str, Any]) -> str:
    namespace = record.get("aad_namespace") or "soc-mind"
    aad = (
        f"{namespace}:enrichment-action:v1:{record['action_code']}:{record['key_id']}"
    ).encode()
    clear = AESGCM(_decode(settings.webhook_secret_encryption_key)).decrypt(
        _decode(record["nonce"]), _decode(record["ciphertext"]), aad
    )
    return clear.decode()


class EnrichmentActionCoordinator:
    BATCHES = "enrichment_action_batches"
    RESULTS = "enrichment_action_results"
    ALERTS = "alerts"
    ACTIONS = "enrichment_actions"

    def __init__(self, producer, logger):
        self.producer = producer
        self.logger = logger
        self._indexed_databases: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._scheduler: asyncio.Task | None = None
        self._instance_id = deterministic_id("worker", id(self), time.time_ns())

    async def _trace_event(
        self,
        phase: str,
        batch: dict[str, Any],
        *,
        decisions: dict[str, Any] | None = None,
    ) -> None:
        if not settings.debug_trace_enabled:
            return
        started_at = batch.get("created_at") or datetime.now(timezone.utc)
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        safe_decisions = json.loads(
            json.dumps(decisions or {}, default=str, separators=(",", ":"))
        )
        event: dict[str, Any] = {
            "span_id": deterministic_id("trace-span", batch["batch_id"]),
            "alert_id": batch["alert_id"],
            "tenant_id": batch["tenant_id"],
            "alert_type": batch["output_message"].get("alert_type"),
            "source_system": batch["output_message"].get("source_system"),
            "stage": "ENRICHMENT_ACTION",
            "sequence": 55,
            "service": "pipeline-enrichment-action",
            "release_sha": settings.app_release_sha,
            "release_version": settings.app_release_version,
            "started_at": started_at.isoformat(),
            "phase": phase,
        }
        if phase == "STARTED":
            trace_input = {
                "batch_id": batch["batch_id"],
                "action_codes": batch["action_codes"],
                "queue_state": "PENDING",
            }
            event.update(
                outcome="RUNNING",
                input_snapshot={
                    "value": trace_input,
                    "truncated": False,
                    "size_bytes": len(canonical_json(trace_input)),
                },
            )
        elif phase == "PROGRESS":
            event.update(outcome="RUNNING", decisions=safe_decisions)
        else:
            completed_at = datetime.now(timezone.utc)
            event.update(
                outcome="SUCCEEDED",
                completed_at=completed_at.isoformat(),
                duration_ms=round((completed_at - started_at).total_seconds() * 1000, 3),
                checks=[
                    {
                        "name": "all_actions_terminal",
                        "outcome": "SUCCEEDED",
                    }
                ],
                decisions=safe_decisions,
            )
        try:
            await self.producer(settings.kafka_trace_topic, event)
        except Exception:
            self.logger.exception("Enrichment action trace publication failed")

    async def start(self) -> None:
        self._scheduler = asyncio.create_task(self._loop(), name="enrichment-action-scheduler")

    async def stop(self) -> None:
        if self._scheduler and not self._scheduler.done():
            self._scheduler.cancel()
            try:
                await self._scheduler
            except asyncio.CancelledError:
                pass
        if self._tasks:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def ensure_indexes(self, db_name: str) -> None:
        if db_name in self._indexed_databases:
            return
        db = get_client()[db_name]
        await db[self.BATCHES].create_index("batch_id", unique=True)
        await db[self.BATCHES].create_index(
            [("status", ASCENDING), ("created_at", ASCENDING)]
        )
        await db[self.RESULTS].create_index("delivery_id", unique=True)
        await db[self.RESULTS].create_index(
            [("batch_id", ASCENDING), ("config_order", ASCENDING)], unique=True
        )
        await db[self.RESULTS].create_index(
            [("status", ASCENDING), ("lease_expires_at", ASCENDING)]
        )
        self._indexed_databases.add(db_name)

    async def queue(
        self,
        *,
        db_name: str,
        tenant_id: str,
        alert: dict[str, Any],
        playbook: dict[str, Any],
        output_message: dict[str, Any],
    ) -> dict[str, Any]:
        await self.ensure_indexes(db_name)
        db = get_client()[db_name]
        playbook_id = str(playbook["playbook_id"])
        playbook_version = int(playbook.get("version") or 1)
        codes = list(playbook.get("enrichment_actions") or [])[:10]
        batch_id = deterministic_id(
            "batch", tenant_id, alert["alert_id"], playbook_id, playbook_version
        )
        now = datetime.now(timezone.utc)
        batch = {
            "batch_id": batch_id,
            "tenant_id": tenant_id,
            "alert_id": str(alert["alert_id"]),
            "playbook_id": playbook_id,
            "playbook_version": playbook_version,
            "action_codes": codes,
            "action_count": len(codes),
            "status": "PENDING",
            "output_message": output_message,
            "created_at": now,
            "updated_at": now,
        }
        await db[self.BATCHES].update_one(
            {"batch_id": batch_id}, {"$setOnInsert": batch}, upsert=True
        )
        for order, code in enumerate(codes):
            delivery_id = deterministic_id(
                "delivery", tenant_id, alert["alert_id"], playbook_id, playbook_version, code
            )
            await db[self.RESULTS].update_one(
                {"delivery_id": delivery_id},
                {
                    "$setOnInsert": {
                        "delivery_id": delivery_id,
                        "batch_id": batch_id,
                        "tenant_id": tenant_id,
                        "alert_id": str(alert["alert_id"]),
                        "playbook_id": playbook_id,
                        "playbook_version": playbook_version,
                        "action_code": code,
                        "config_order": order,
                        "status": "PENDING",
                        "queued_at": now,
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
            )
        await db[self.ALERTS].update_one(
            {"alert_id": str(alert["alert_id"])},
            {
                "$set": {
                    "enrichment_action_batch_id": batch_id,
                    "enrichment_action_status": "PENDING",
                    "updated_at": now,
                }
            },
        )
        await self._trace_event("STARTED", batch)
        # Recover a crash that happened after the last action became terminal
        # but before the batch was promoted to READY.
        await self._complete_batch(db, batch_id)
        return {"batch_id": batch_id, "action_codes": codes, "status": "PENDING"}

    async def _loop(self) -> None:
        while True:
            try:
                self._tasks = {task for task in self._tasks if not task.done()}
                capacity = max(0, settings.enrichment_action_max_concurrency - len(self._tasks))
                if capacity:
                    tenants = await get_database()["tenants"].find(
                        {"status": "ACTIVE"}, {"_id": 0, "db_name": 1}
                    ).to_list(length=None)
                    for tenant in tenants:
                        if capacity <= 0:
                            break
                        db_name = str(tenant["db_name"])
                        await self.ensure_indexes(db_name)
                        claimed = await self._claim(db_name, capacity)
                        for result in claimed:
                            task = asyncio.create_task(self._execute(db_name, result))
                            self._tasks.add(task)
                            capacity -= 1
                await self._publish_ready_batches()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("Enrichment action scheduler iteration failed")
            await asyncio.sleep(settings.enrichment_action_scheduler_interval_seconds)

    async def _claim(self, db_name: str, limit: int) -> list[dict[str, Any]]:
        db = get_client()[db_name]
        claimed: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for _ in range(limit):
            record = await db[self.RESULTS].find_one_and_update(
                {
                    "$or": [
                        {"status": "PENDING"},
                        {"status": "RUNNING", "lease_expires_at": {"$lte": now}},
                    ]
                },
                {
                    "$set": {
                        "status": "RUNNING",
                        "worker_id": self._instance_id,
                        "started_at": now,
                        "updated_at": now,
                        "last_heartbeat_at": now,
                        "lease_expires_at": now + timedelta(seconds=1920),
                    },
                    "$inc": {"claim_count": 1},
                },
                sort=[("queued_at", ASCENDING), ("config_order", ASCENDING)],
                return_document=ReturnDocument.AFTER,
            )
            if not record:
                break
            claimed.append(record)
        return claimed

    async def _action(self, record: dict[str, Any]) -> dict[str, Any] | None:
        return await get_database()[self.ACTIONS].find_one(
            {"action_code": record["action_code"]}
        )

    @staticmethod
    def _authorized(action: dict[str, Any], tenant_id: str) -> bool:
        return action.get("tenant_scope") == "ALL_TENANTS" or (
            action.get("tenant_scope") == "SELECTED_TENANTS"
            and tenant_id in (action.get("tenant_ids") or [])
        )

    async def _heartbeat(self, db: Any, delivery_id: str, lease_seconds: int) -> None:
        while True:
            await asyncio.sleep(30)
            now = datetime.now(timezone.utc)
            await db[self.RESULTS].update_one(
                {"delivery_id": delivery_id, "status": "RUNNING", "worker_id": self._instance_id},
                {"$set": {
                    "last_heartbeat_at": now,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "updated_at": now,
                }},
            )
            result = await db[self.RESULTS].find_one(
                {"delivery_id": delivery_id}, {"_id": 0, "batch_id": 1}
            )
            if result:
                await self._publish_progress(db, str(result["batch_id"]))

    async def _publish_progress(self, db: Any, batch_id: str) -> None:
        batch = await db[self.BATCHES].find_one({"batch_id": batch_id}, {"_id": 0})
        if not batch:
            return
        results = await db[self.RESULTS].find(
            {"batch_id": batch_id}, {"_id": 0, "context_text": 0, "ciphertext": 0, "nonce": 0}
        ).sort("config_order", ASCENDING).to_list(length=None)
        await self._trace_event(
            "PROGRESS",
            batch,
            decisions={
                "batch_id": batch_id,
                "queue_state": batch.get("status"),
                "actions": results,
            },
        )

    async def _execute(self, db_name: str, record: dict[str, Any]) -> None:
        db = get_client()[db_name]
        delivery_id = str(record["delivery_id"])
        started = time.monotonic()
        await db[self.BATCHES].update_one(
            {"batch_id": record["batch_id"], "status": "PENDING"},
            {"$set": {"status": "RUNNING", "updated_at": datetime.now(timezone.utc)}},
        )
        action = await self._action(record)
        if (
            not action
            or action.get("deleted_at") is not None
            or not action.get("enabled")
            or not self._authorized(action, record["tenant_id"])
        ):
            metadata = {}
            if action:
                metadata = {
                    "configuration_checksum": action.get("configuration_checksum"),
                    "key_id": action.get("key_id"),
                }
            await self._finish(
                db,
                record,
                "SKIPPED",
                started,
                error_type="ACTION_UNAVAILABLE",
                **metadata,
            )
            return
        timeout_seconds = max(1, min(1800, int(action.get("timeout_seconds") or 300)))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
        lease_seconds = timeout_seconds + 120
        await db[self.RESULTS].update_one(
            {"delivery_id": delivery_id, "worker_id": self._instance_id},
            {"$set": {
                "configuration_checksum": action["configuration_checksum"],
                "key_id": action["key_id"],
                "timeout_seconds": timeout_seconds,
                "deadline_at": deadline,
                "lease_expires_at": datetime.now(timezone.utc) + timedelta(seconds=lease_seconds),
            }},
        )
        heartbeat = asyncio.create_task(self._heartbeat(db, delivery_id, lease_seconds))
        await self._publish_progress(db, str(record["batch_id"]))
        try:
            batch = await db[self.BATCHES].find_one({"batch_id": record["batch_id"]})
            if not batch:
                raise ValueError("ACTION_BATCH_MISSING")
            output = batch["output_message"]
            sent_at = datetime.now(timezone.utc)
            body = {
                "spec_version": "1.0",
                "delivery_id": delivery_id,
                "sent_at": sent_at.isoformat().replace("+00:00", "Z"),
                "tenant_id": record["tenant_id"],
                "action": {"code": record["action_code"]},
                "alert": {
                    "alert_id": output["alert_id"],
                    "alert_type": output["alert_type"],
                    "source_system": output["source_system"],
                    "fingerprint": output["fingerprint"],
                    "normalized_payload": output.get("normalized_payload") or {},
                },
                "playbook": {
                    "playbook_id": record["playbook_id"],
                    "version": int(record["playbook_version"]),
                },
                "release": {
                    "version": settings.app_release_version,
                    "sha": settings.app_release_sha,
                },
            }
            raw = canonical_json(body)
            if len(raw) > settings.enrichment_action_max_request_bytes:
                raise ValueError("ACTION_REQUEST_TOO_LARGE")
            timestamp = str(int(sent_at.timestamp()))
            signed = timestamp.encode() + b"." + delivery_id.encode() + b"." + raw
            signature = hmac.new(
                decrypt_action_secret(action).encode(), signed, hashlib.sha256
            ).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "X-TierX-Action-Version": "1",
                "X-TierX-Delivery-ID": delivery_id,
                "X-TierX-Timestamp": timestamp,
                "X-TierX-Key-ID": action["key_id"],
                "X-TierX-Signature": f"v1={signature}",
                "X-SOC-Mind-Action-Version": "1",
                "X-SOC-Mind-Delivery-ID": delivery_id,
                "X-SOC-Mind-Timestamp": timestamp,
                "X-SOC-Mind-Key-ID": action["key_id"],
                "X-SOC-Mind-Signature": f"v1={signature}",
            }
            url = await validate_public_https_url(str(action["url"]))
            timeout = httpx.Timeout(timeout_seconds, connect=10, write=10, pool=10)
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                    async with client.stream("POST", url, content=raw, headers=headers) as response:
                        if response.status_code != 200:
                            raise ValueError("ACTION_HTTP_ERROR")
                        content_type = response.headers.get("content-type", "").lower()
                        if "application/json" not in content_type:
                            raise ValueError("ACTION_RESPONSE_INVALID_CONTENT_TYPE")
                        chunks: list[bytes] = []
                        received = 0
                        async for chunk in response.aiter_bytes():
                            received += len(chunk)
                            if received > settings.enrichment_action_max_response_bytes:
                                raise ValueError("ACTION_RESPONSE_TOO_LARGE")
                            chunks.append(chunk)
            try:
                response_body = json.loads(b"".join(chunks))
            except Exception as exc:
                raise ValueError("ACTION_RESPONSE_INVALID_JSON") from exc
            outcome = response_body.get("outcome") if isinstance(response_body, dict) else None
            context = response_body.get("context_text") if isinstance(response_body, dict) else None
            if not isinstance(response_body, dict):
                raise ValueError("ACTION_RESPONSE_INVALID_SCHEMA")
            if (
                response_body.get("spec_version") != "1.0"
                or response_body.get("delivery_id") != delivery_id
            ):
                raise ValueError("ACTION_RESPONSE_DELIVERY_MISMATCH")
            if not isinstance(outcome, str) or not __import__("re").fullmatch(
                r"[A-Z][A-Z0-9_]{0,63}", outcome
            ):
                raise ValueError("ACTION_RESPONSE_INVALID_OUTCOME")
            if not isinstance(context, str) or not context.strip():
                raise ValueError("ACTION_RESPONSE_INVALID_CONTEXT")
            context_bytes = context.encode("utf-8")
            if len(context_bytes) > settings.enrichment_action_max_context_bytes:
                raise ValueError("ACTION_RESPONSE_TOO_LARGE")
            await self._finish(
                db, record, "SUCCEEDED", started,
                outcome=outcome,
                context_text=context,
                response_sha256=hashlib.sha256(context_bytes).hexdigest(),
                response_size_bytes=len(context_bytes),
                configuration_checksum=action["configuration_checksum"],
                key_id=action["key_id"],
            )
        except TimeoutError:
            await self._finish(db, record, "FAILED", started, error_type="ACTION_TIMEOUT")
        except httpx.TimeoutException:
            await self._finish(db, record, "FAILED", started, error_type="ACTION_TIMEOUT")
        except httpx.RequestError:
            await self._finish(db, record, "FAILED", started, error_type="ACTION_REQUEST_FAILED")
        except ValueError as exc:
            error = str(exc) if str(exc).startswith("ACTION_") else "ACTION_FAILURE"
            await self._finish(db, record, "FAILED", started, error_type=error)
        except Exception:
            self.logger.exception("Enrichment action failed delivery_id=%s", delivery_id)
            await self._finish(db, record, "FAILED", started, error_type="ACTION_FAILURE")
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

    async def _finish(self, db: Any, record: dict[str, Any], status: str, started: float, **values: Any) -> None:
        now = datetime.now(timezone.utc)
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        await db[self.RESULTS].update_one(
            {"delivery_id": record["delivery_id"], "worker_id": self._instance_id},
            {"$set": {
                "status": status,
                "duration_ms": duration_ms,
                "completed_at": now,
                "updated_at": now,
                "lease_expires_at": None,
                **values,
            }},
        )
        await get_database()[self.ACTIONS].update_one(
            {"action_code": record["action_code"]},
            {"$set": {
                "last_used_at": now,
                "last_status": status,
                "last_duration_ms": duration_ms,
                "last_error_type": values.get("error_type"),
            }},
        )
        await self._publish_progress(db, str(record["batch_id"]))
        await self._complete_batch(db, str(record["batch_id"]))

    async def _complete_batch(self, db: Any, batch_id: str) -> None:
        batch = await db[self.BATCHES].find_one({"batch_id": batch_id})
        if not batch or batch.get("status") in {"READY", "PUBLISHING", "PUBLISHED"}:
            return
        results = await db[self.RESULTS].find({"batch_id": batch_id}, {"_id": 0}).sort("config_order", ASCENDING).to_list(length=None)
        if len(results) != int(batch.get("action_count") or 0) or any(
            result.get("status") not in TERMINAL_STATUSES for result in results
        ):
            return
        now = datetime.now(timezone.utc)
        safe_results = [
            {key: value for key, value in result.items() if key not in {"worker_id", "lease_expires_at"}}
            for result in results
        ]
        changed = await db[self.BATCHES].update_one(
            {"batch_id": batch_id, "status": {"$in": ["PENDING", "RUNNING"]}},
            {"$set": {"status": "READY", "completed_at": now, "updated_at": now}},
        )
        if not changed.modified_count:
            return
        await db[self.ALERTS].update_one(
            {"alert_id": batch["alert_id"]},
            {"$set": {
                "enrichment_action_status": "COMPLETED",
                "enrichment_action_results": safe_results,
                "kafka_state": "ENRICHED",
                "enriched": True,
                "updated_at": now,
            }},
        )
        decisions = {
            "batch_id": batch_id,
            "queue_state": "READY",
            "actions": [
                {
                    key: value
                    for key, value in result.items()
                    if key not in {"context_text", "_id"}
                }
                for result in safe_results
            ],
        }
        await self._trace_event("COMPLETED", batch, decisions=decisions)

    async def _publish_ready_batches(self) -> None:
        tenants = await get_database()["tenants"].find(
            {"status": "ACTIVE"}, {"_id": 0, "db_name": 1}
        ).to_list(length=None)
        for tenant in tenants:
            db = get_client()[str(tenant["db_name"])]
            batch = await db[self.BATCHES].find_one_and_update(
                {
                    "$or": [
                        {"status": "READY"},
                        {
                            "status": "PUBLISHING",
                            "updated_at": {
                                "$lte": datetime.now(timezone.utc) - timedelta(seconds=60)
                            },
                        },
                    ]
                },
                {"$set": {"status": "PUBLISHING", "updated_at": datetime.now(timezone.utc)}},
                sort=[("created_at", ASCENDING)],
                return_document=ReturnDocument.AFTER,
            )
            if not batch:
                continue
            try:
                await self.producer(settings.kafka_enriched_topic, batch["output_message"])
                await db[self.BATCHES].update_one(
                    {"batch_id": batch["batch_id"], "status": "PUBLISHING"},
                    {"$set": {"status": "PUBLISHED", "published_at": datetime.now(timezone.utc)}},
                )
            except Exception:
                self.logger.exception("Could not publish completed enrichment action batch")
                await db[self.BATCHES].update_one(
                    {"batch_id": batch["batch_id"], "status": "PUBLISHING"},
                    {"$set": {"status": "READY", "updated_at": datetime.now(timezone.utc)}},
                )
