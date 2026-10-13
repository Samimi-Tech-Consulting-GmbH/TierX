"""Durable acyclic graph scheduler with idempotent routing and paired joins."""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pymongo import ReturnDocument
from tierx_runtime import boolean, env_value, installed
from tierx_workflows import checksum
from tierx_workflows.llm import ModelError
from app.db.mongodb import get_client, get_database
from app.workflows.tools import Tools, NodeFailure, NodeWaiting

logger = logging.getLogger("workflow-v2")


def now():
    return datetime.now(timezone.utc)


class Engine:
    def __init__(self):
        self.owner = str(uuid4())
        self.tasks = set()
        self.stopping = False
        self.tools = Tools()
        self.tenant_cursor = 0

    async def enqueue(self, db, run, node_id, path=(), ancestors=None, error=None):
        job_id = checksum([run["run_id"], node_id, list(path)])
        row = {
            "job_id": job_id,
            "run_id": run["run_id"],
            "node_id": node_id,
            "path": list(path),
            "ancestors": ancestors or {},
            "error_input": error,
            "state": "PENDING",
            "created_at": now(),
            "routed": False,
        }
        await db.v2_jobs.update_one(
            {"job_id": job_id}, {"$setOnInsert": row}, upsert=True
        )

    async def initialize(self, db, run):
        entry = next(node for node in run["graph"]["nodes"] if node["type"] == "entry")
        await db.v2_alerts.update_one(
            {"alert_id": run["alert_id"]},
            {
                "$setOnInsert": {
                    **run["input"],
                    "alert_id": run["alert_id"],
                    "tenant_id": run["tenant_id"],
                    "cohort": run["cohort"],
                    "created_at": run["created_at"],
                    "status": "RECEIVED",
                    "kafka_state": "RECEIVED",
                    "run_id": run["run_id"],
                }
            },
            upsert=True,
        )
        await self.enqueue(db, run, entry["id"])
        await db.v2_runs.update_one(
            {"run_id": run["run_id"], "state": "PENDING"},
            {"$set": {"state": "RUNNING", "started_at": now()}},
        )

    async def heartbeat(self, db, job):
        while True:
            await asyncio.sleep(30)
            await db.v2_jobs.update_one(
                {
                    "job_id": job["job_id"],
                    "lease_owner": self.owner,
                    "state": "RUNNING",
                },
                {
                    "$set": {
                        "lease_expires_at": now() + timedelta(seconds=1920),
                        "heartbeat_at": now(),
                    }
                },
            )

    async def execute(self, db, job):
        heart = asyncio.create_task(self.heartbeat(db, job))
        started = time.monotonic()
        try:
            run = await db.v2_runs.find_one({"run_id": job["run_id"]})
            if not run or run["state"] in {"FAILED", "CANCELLED"}:
                await db.v2_jobs.update_one(
                    {"job_id": job["job_id"], "lease_owner": self.owner},
                    {"$set": {"state": "CANCELLED", "routed": True}},
                )
                return
            node = next(n for n in run["graph"]["nodes"] if n["id"] == job["node_id"])
            output, port = await self.tools.execute(db, run, node, job)
            import json

            if len(json.dumps(output, default=str).encode()) > 256 * 1024:
                raise NodeFailure("NODE_OUTPUT_TOO_LARGE")
            result = {"state": "SUCCEEDED", "output": output, "port": port}
        except NodeWaiting as exc:
            await db.v2_jobs.update_one(
                {"job_id": job["job_id"], "lease_owner": self.owner},
                {
                    "$set": {
                        "state": "WAITING",
                        "wait_reason": exc.code,
                        "lease_expires_at": now() + timedelta(seconds=5),
                    }
                },
            )
            return
        except (NodeFailure, ModelError) as exc:
            result = {
                "state": "FAILED",
                "error": {
                    "type": exc.code if isinstance(exc, NodeFailure) else str(exc)
                },
                "port": "error",
            }
        except Exception:
            logger.warning("Node failed run=%s node=%s", job["run_id"], job["node_id"])
            result = {
                "state": "FAILED",
                "error": {"type": "NODE_EXECUTION_FAILURE"},
                "port": "error",
            }
        finally:
            heart.cancel()
            await asyncio.gather(heart, return_exceptions=True)
            await db.v2_clusters.update_many(
                {
                    "v2_analysis_owner": job["job_id"],
                    "v2_analysis_lease_owner": self.owner,
                },
                {
                    "$unset": {
                        "v2_analysis_owner": "",
                        "v2_analysis_lease_owner": "",
                        "v2_analysis_expires_at": "",
                    }
                },
            )
        result.update(
            completed_at=now(),
            duration_ms=round((time.monotonic() - started) * 1000, 3),
            routed=False,
        )
        await db.v2_jobs.update_one(
            {"job_id": job["job_id"], "lease_owner": self.owner, "state": "RUNNING"},
            {"$set": result},
        )

    async def route(self, db, job):
        run = await db.v2_runs.find_one({"run_id": job["run_id"]})
        node = next(n for n in run["graph"]["nodes"] if n["id"] == job["node_id"])
        ancestry = {
            **job.get("ancestors", {}),
            node["id"]: {
                "job_id": job["job_id"],
                "state": job["state"],
                "error": job.get("error"),
            },
        }
        if node["type"] in {"complete", "dead_letter"}:
            handled = await db.v2_jobs.count_documents(
                {
                    "run_id": run["run_id"],
                    "state": "FAILED",
                    "handled_by": {"$exists": True},
                }
            )
            state = (
                "FAILED"
                if node["type"] == "dead_letter"
                else "SUCCEEDED_WITH_WARNINGS" if handled else "SUCCEEDED"
            )
            await db.v2_runs.update_one(
                {"run_id": run["run_id"], "state": {"$in": ["RUNNING", "PENDING"]}},
                {
                    "$set": {
                        "state": state,
                        "completed_at": now(),
                        "terminal_node": node["id"],
                    }
                },
            )
        else:
            edges = [
                e
                for e in run["graph"]["edges"]
                if e["source"] == node["id"]
                and (
                    node["type"] == "fork"
                    or e.get("sourceHandle", "success") == job["port"]
                )
            ]
            if not edges:
                if job.get("path"):
                    fork_id = job["path"][-1]["fork_id"]
                    fork = next(n for n in run["graph"]["nodes"] if n["id"] == fork_id)
                    await self.arrive(
                        db,
                        run,
                        fork["config"]["join_id"],
                        job["path"],
                        {
                            **ancestry,
                            "_unhandled_error": job.get(
                                "error", {"type": "UNHANDLED_OUTPUT"}
                            ),
                        },
                    )
                else:
                    await db.v2_runs.update_one(
                        {"run_id": run["run_id"]},
                        {
                            "$set": {
                                "state": "FAILED",
                                "completed_at": now(),
                                "error": job.get("error", {"type": "UNHANDLED_OUTPUT"}),
                            }
                        },
                    )
            for edge in edges:
                path = list(job.get("path", []))
                if node["type"] == "fork":
                    path.append({"fork_id": node["id"], "branch": edge["sourceHandle"]})
                target = next(
                    n for n in run["graph"]["nodes"] if n["id"] == edge["target"]
                )
                if target["type"] == "join":
                    await self.arrive(db, run, target["id"], path, ancestry)
                else:
                    error = (
                        {
                            **job.get("error", {}),
                            "node_id": node["id"],
                            "job_id": job["job_id"],
                        }
                        if job["port"] == "error"
                        else None
                    )
                    await self.enqueue(db, run, target["id"], path, ancestry, error)
        await db.v2_jobs.update_one(
            {"job_id": job["job_id"]}, {"$set": {"routed": True}}
        )

    async def arrive(self, db, run, target_id, path, ancestry):
        target = next(n for n in run["graph"]["nodes"] if n["id"] == target_id)
        if not path or path[-1]["fork_id"] != target["config"]["fork_id"]:
            raise ValueError("Join nesting mismatch")
        fork = next(n for n in run["graph"]["nodes"] if n["id"] == path[-1]["fork_id"])
        join_key = checksum([run["run_id"], target_id, path[:-1]])
        await db.v2_joins.update_one(
            {"join_key": join_key},
            {
                "$set": {f"branches.{path[-1]['branch']}": ancestry},
                "$setOnInsert": {"run_id": run["run_id"]},
            },
            upsert=True,
        )
        join = await db.v2_joins.find_one({"join_key": join_key})
        if all(
            branch in join.get("branches", {}) for branch in fork["config"]["branches"]
        ):
            branches = {
                branch: join["branches"][branch]
                for branch in fork["config"]["branches"]
            }
            await self.enqueue(db, run, target_id, path[:-1], {"branches": branches})

    async def tick(self):
        tenants = (
            await get_database()
            .tenants.find({"status": "ACTIVE"}, {"tenant_id": 1, "db_name": 1})
            .to_list(None)
        )
        if tenants:
            offset = self.tenant_cursor % len(tenants)
            tenants = tenants[offset:] + tenants[:offset]
            self.tenant_cursor += 1
        for tenant in tenants:
            db = get_client()[tenant["db_name"]]
            await db.v2_jobs.create_index("job_id", unique=True)
            await db.v2_joins.create_index("join_key", unique=True)
            for run in (
                await db.v2_runs.find({"state": "PENDING"}).limit(100).to_list(None)
            ):
                await self.initialize(db, run)
            await self.tools.schedule(db, tenant)
            for job in (
                await db.v2_jobs.find(
                    {"state": {"$in": ["SUCCEEDED", "FAILED"]}, "routed": False}
                )
                .limit(100)
                .to_list(None)
            ):
                await self.route(db, job)
            while len(self.tasks) < 5 and not self.stopping:
                job = await db.v2_jobs.find_one_and_update(
                    {
                        "$or": [
                            {"state": "PENDING"},
                            {
                                "state": {"$in": ["RUNNING", "WAITING"]},
                                "lease_expires_at": {"$lte": now()},
                            },
                        ]
                    },
                    {
                        "$set": {
                            "state": "RUNNING",
                            "lease_owner": self.owner,
                            "lease_expires_at": now() + timedelta(seconds=1920),
                            "started_at": now(),
                        }
                    },
                    return_document=ReturnDocument.AFTER,
                    sort=[("created_at", 1), ("job_id", 1)],
                )
                if not job:
                    break
                if job.get("heartbeat_at") or job.get("wait_reason"):
                    await db.v2_jobs.update_one(
                        {"job_id": job["job_id"], "lease_owner": self.owner},
                        {"$set": {"reclaimed_at": now()}},
                    )
                task = asyncio.create_task(self.execute(db, job))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

    async def run(self):
        if not boolean(env_value("ingestion_v2_enabled") or False):
            logger.info("Ingestion V2 disabled")
            return
        try:
            while not self.stopping:
                if installed(
                    await get_database().platform_configuration.find_one(
                        {"_id": "installation"}
                    )
                ):
                    try:
                        await self.tick()
                    except Exception:
                        logger.warning(
                            "V2 scheduling failed; retrying without touching V1"
                        )
                await asyncio.sleep(1)
        finally:
            self.stopping = True
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
