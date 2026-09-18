import asyncio
import os

# Canonical TierX environment variables override current unprefixed names;
# legacy SOC_MIND_* aliases remain permanent for existing deployments.
for _key, _value in tuple(os.environ.items()):
    if _key.startswith("TIERX_"):
        os.environ[_key.removeprefix("TIERX_")] = _value
for _key, _value in tuple(os.environ.items()):
    if _key.startswith("SOC_MIND_"):
        _unprefixed = _key.removeprefix("SOC_MIND_")
        if _unprefixed not in os.environ and f"TIERX_{_unprefixed}" not in os.environ:
            os.environ[_unprefixed] = _value
import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from app.db.mongodb import DatabaseManager
from app.api.v1.admin.tenants import router as admin_tenants_router
from app.api.v1.admin.users import router as admin_users_router
from app.api.v1.admin.debug import router as admin_debug_router
from app.api.v1.admin.dashboard import router as admin_dashboard_router
from app.api.v1.admin.platform_lists import router as admin_platform_lists_router
from app.api.v1.admin.jira_integrations import router as admin_jira_integrations_router
from app.api.v1.admin.enrichment_actions import (
    router as admin_enrichment_actions_router,
)
from app.api.v1.auth import router as auth_router
from app.api.v1.tenant_users import router as tenant_users_router
from app.api.v1.tenant_info import router as tenant_info_router
from app.api.v1.playbooks import router as playbooks_router
from app.api.v1.schema_registry import router as schema_registry_router
from app.api.v1.clusters import router as clusters_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.jira_integrations import router as jira_integrations_router
from app.api.v1.webhook_signing import router as webhook_signing_router
from app.api.v1.example_webhook import router as example_webhook_router
from app.api.v1.enrichment_actions import router as enrichment_actions_router
from app.api.v1.knowledge_base import router as knowledge_base_router
from app.services.analysis_service import AnalysisService
from app.services.playbook_service import PlaybookValidationError
from app.services.alert_type_schema_service import AlertTypeSchemaValidationError
from app.services.tenant_service import TenantService
from app.services.user_service import UserService
from app.services.dashboard_service import PlatformDashboardService
from app.services.platform_list_service import PlatformListService
from app.services.jira_integration_service import JiraIntegrationService
from app.services.webhook_signing_service import WebhookSigningService
from app.services.enrichment_action_service import EnrichmentActionService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.core.tenant_resolver import tenant_resolver
from app.core.errors import (
    TenantSuspendedError,
    ResourceNotFoundError,
    DuplicateResourceError,
)

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

required = (
    "MONGO_URL",
    "JWT_SECRET_KEY",
    "PLATFORM_ADMIN_EMAIL",
    "PLATFORM_ADMIN_PASSWORD",
)
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

# This feature encrypts tenant signing credentials. Refuse to start in an
# enabled-but-undecryptable state rather than accepting secrets we cannot use.
WebhookSigningService.validate_configuration()
EnrichmentActionService.validate_configuration()


@asynccontextmanager
async def lifespan(app: FastAPI):
    jira_cleanup_task = None
    try:
        DatabaseManager.initialize()
        TenantService.initialize_schema()
        UserService.seed_platform_admin(
            email=os.environ["PLATFORM_ADMIN_EMAIL"],
            password=os.environ["PLATFORM_ADMIN_PASSWORD"],
        )
        AnalysisService.ensure_system_prompt()
        PlatformDashboardService.ensure_indexes()
        PlatformListService.ensure_indexes()
        JiraIntegrationService.ensure_indexes()
        EnrichmentActionService.ensure_indexes()
        KnowledgeBaseService.ensure_indexes()
        jira_cleanup_task = asyncio.create_task(
            JiraIntegrationService.cleanup_loop(), name="jira-quarantine-cleanup"
        )
        if os.getenv("DEBUG_TRACE_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            from app.services.debug_trace_service import DebugTraceService

            DebugTraceService.ensure_indexes()
    except Exception as e:
        print(f"Failed to initialize database or schema: {e}")
    yield
    if jira_cleanup_task:
        jira_cleanup_task.cancel()
        try:
            await jira_cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="TierX API",
    description="Tenant-aware security alert processing and analysis API.",
    version=os.getenv("APP_RELEASE_VERSION", "development"),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(TenantSuspendedError)
async def suspended_error_handler(request: Request, exc: TenantSuspendedError):
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)}
    )


@app.exception_handler(ResourceNotFoundError)
async def not_found_handler(request: Request, exc: ResourceNotFoundError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(DuplicateResourceError)
async def duplicate_handler(request: Request, exc: DuplicateResourceError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(PlaybookValidationError)
async def playbook_validation_handler(request: Request, exc: PlaybookValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": {"errors": exc.errors}},
    )


@app.exception_handler(AlertTypeSchemaValidationError)
async def alert_schema_validation_handler(
    request: Request, exc: AlertTypeSchemaValidationError
):
    return JSONResponse(
        status_code=422,
        content={"detail": {"errors": exc.errors}},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


app.include_router(auth_router, prefix="/api/v1")
app.include_router(playbooks_router, prefix="/api/v1")
app.include_router(schema_registry_router, prefix="/api/v1")
app.include_router(admin_tenants_router, prefix="/api/v1/admin")
app.include_router(admin_users_router, prefix="/api/v1/admin")
app.include_router(admin_debug_router, prefix="/api/v1/admin")
app.include_router(admin_dashboard_router, prefix="/api/v1/admin")
app.include_router(admin_platform_lists_router, prefix="/api/v1/admin")
app.include_router(admin_jira_integrations_router, prefix="/api/v1/admin")
app.include_router(admin_enrichment_actions_router, prefix="/api/v1/admin")
app.include_router(tenant_users_router, prefix="/api/v1")
app.include_router(tenant_info_router, prefix="/api/v1")
app.include_router(clusters_router, prefix="/api/v1")
app.include_router(analysis_router, prefix="/api/v1")
app.include_router(jira_integrations_router, prefix="/api/v1")
app.include_router(webhook_signing_router, prefix="/api/v1")
app.include_router(example_webhook_router, prefix="/api/v1")
app.include_router(enrichment_actions_router, prefix="/api/v1")
app.include_router(knowledge_base_router, prefix="/api/v1")


def verify_tenant_active(tenant_id: str):
    status_val = tenant_resolver.get_status(tenant_id)
    if status_val == "SUSPENDED":
        raise TenantSuspendedError(tenant_id)
    return tenant_id


@app.post("/api/v1/ingest/{tenant_id}/events")
async def mock_ingest_events(tenant_id: str = Depends(verify_tenant_active)):
    return {"msg": f"Ingested for {tenant_id}"}


MONGO_URL = os.environ["MONGO_URL"]
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:latest")
OLLAMA_MODEL_DIGEST = os.getenv("OLLAMA_MODEL_DIGEST", "")
LLM_ANALYSIS_ENABLED = os.getenv("LLM_ANALYSIS_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
APP_RELEASE_SHA = os.getenv("APP_RELEASE_SHA", "development")
APP_RELEASE_VERSION = os.getenv("APP_RELEASE_VERSION", "development")
KNOWLEDGE_BASE_PROCESSING_ENABLED = os.getenv(
    "KNOWLEDGE_BASE_PROCESSING_ENABLED", "false"
).lower() in {"1", "true", "yes", "on"}
KNOWLEDGE_BASE_RETRIEVAL_ENABLED = os.getenv(
    "KNOWLEDGE_BASE_RETRIEVAL_ENABLED", "false"
).lower() in {"1", "true", "yes", "on"}


@app.get("/api/v1/health")
async def health_check():
    components = {}
    overall_status = "HEALTHY"

    try:
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        components["mongodb"] = "green"
        if KNOWLEDGE_BASE_PROCESSING_ENABLED:
            heartbeat = client.soc_mind_platform.service_heartbeats.find_one(
                {"service": "knowledge-base-processor"}
            )
            seen_at = heartbeat.get("seen_at") if heartbeat else None
            if seen_at and seen_at.tzinfo is None:
                seen_at = seen_at.replace(tzinfo=timezone.utc)
            components["knowledge_base_processor"] = (
                "green"
                if seen_at
                and seen_at >= datetime.now(timezone.utc) - timedelta(seconds=30)
                else "red"
            )
            if components["knowledge_base_processor"] == "red":
                overall_status = "UNHEALTHY"
    except Exception:
        components["mongodb"] = "red"
        overall_status = "UNHEALTHY"

    try:
        async with httpx.AsyncClient(timeout=2.0) as httpx_client:
            response = await httpx_client.get(f"{OLLAMA_URL}/api/tags")
            if response.status_code == 200:
                models = response.json().get("models") or []
                selected = next(
                    (item for item in models if item.get("name") == OLLAMA_MODEL),
                    None,
                )
                digest_matches = bool(selected) and (
                    not OLLAMA_MODEL_DIGEST
                    or selected.get("digest") == OLLAMA_MODEL_DIGEST
                )
                components["ollama"] = "green" if digest_matches else "red"
                components["ollama_model"] = (
                    OLLAMA_MODEL if digest_matches else "missing-or-digest-mismatch"
                )
                if not digest_matches:
                    overall_status = "UNHEALTHY"
            else:
                components["ollama"] = "red"
                overall_status = "UNHEALTHY"
    except Exception:
        components["ollama"] = "red"
        overall_status = "UNHEALTHY"

    return {
        "status": overall_status,
        "components": components,
        "llm_analysis_enabled": LLM_ANALYSIS_ENABLED,
        "playbook_context_webhooks_enabled": WebhookSigningService.enabled(),
        "enrichment_actions_enabled": EnrichmentActionService.enabled(),
        "knowledge_base_processing_enabled": KNOWLEDGE_BASE_PROCESSING_ENABLED,
        "knowledge_base_retrieval_enabled": KNOWLEDGE_BASE_RETRIEVAL_ENABLED,
        "release_version": APP_RELEASE_VERSION,
        "release_sha": APP_RELEASE_SHA,
    }
