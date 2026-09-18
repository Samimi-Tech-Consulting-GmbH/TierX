#!/usr/bin/env python3
"""Guarded rollback helper for durable enrichment-action batches."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer

from app.core.config import settings
from app.db.mongodb import close_client, get_client, get_database


async def main(apply: bool) -> int:
    tenants = await get_database()["tenants"].find(
        {"status": "ACTIVE"}, {"_id": 0, "tenant_id": 1, "db_name": 1}
    ).to_list(length=None)
    pending: list[tuple[dict, dict]] = []
    for tenant in tenants:
        db = get_client()[tenant["db_name"]]
        batches = await db["enrichment_action_batches"].find(
            {"status": {"$in": ["PENDING", "RUNNING", "READY", "PUBLISHING"]}},
            {"_id": 0},
        ).to_list(length=None)
        pending.extend((tenant, batch) for batch in batches)

    print(json.dumps({"pending_batches": len(pending), "apply": apply}))
    if not apply or not pending:
        await close_client()
        return 0

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda value: json.dumps(value).encode(),
        key_serializer=lambda value: value.encode(),
    )
    await producer.start()
    try:
        for tenant, batch in pending:
            db = get_client()[tenant["db_name"]]
            now = datetime.now(timezone.utc)
            await db["enrichment_action_results"].update_many(
                {
                    "batch_id": batch["batch_id"],
                    "status": {"$in": ["PENDING", "RUNNING"]},
                },
                {
                    "$set": {
                        "status": "SKIPPED",
                        "error_type": "FEATURE_DISABLED_BY_OPERATOR",
                        "completed_at": now,
                        "updated_at": now,
                        "lease_expires_at": None,
                    }
                },
            )
            results = await db["enrichment_action_results"].find(
                {"batch_id": batch["batch_id"]}, {"_id": 0, "worker_id": 0}
            ).sort("config_order", 1).to_list(length=None)
            await db["alerts"].update_one(
                {"alert_id": batch["alert_id"]},
                {
                    "$set": {
                        "enrichment_action_status": "COMPLETED",
                        "enrichment_action_results": results,
                        "kafka_state": "ENRICHED",
                        "enriched": True,
                        "updated_at": now,
                    }
                },
            )
            await producer.send_and_wait(
                settings.kafka_enriched_topic,
                batch["output_message"],
                key=str(batch["tenant_id"]),
            )
            await db["enrichment_action_batches"].update_one(
                {"batch_id": batch["batch_id"]},
                {
                    "$set": {
                        "status": "PUBLISHED",
                        "completed_at": now,
                        "published_at": now,
                        "rollback_skip": True,
                        "updated_at": now,
                    }
                },
            )
    finally:
        await producer.stop()
        await close_client()
    print(json.dumps({"skipped_and_published": len(pending)}))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != "SKIP_PENDING_ENRICHMENT_ACTIONS":
        parser.error(
            "--apply requires --confirm SKIP_PENDING_ENRICHMENT_ACTIONS"
        )
    raise SystemExit(asyncio.run(main(args.apply)))
