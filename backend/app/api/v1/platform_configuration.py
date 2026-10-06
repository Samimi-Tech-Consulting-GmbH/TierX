from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from tierx_runtime import DEFAULTS, effective, installed, validate
from app.api.dependencies.auth import require_platform_admin
from app.services.platform_configuration_service import PlatformConfigurationService as Service

router = APIRouter(tags=["Installation and Platform Settings"])


class Values(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_url: str = Field("http://localhost:8080", max_length=2048)
    ollama_url: str = Field("http://ollama:11434", max_length=2048)
    ollama_model: str = Field("phi3:latest", max_length=256)
    llm_analysis_enabled: bool = False
    correlation_enabled: bool = False
    knowledge_base_processing_enabled: bool = False
    knowledge_base_retrieval_enabled: bool = False


class Complete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=12, max_length=72)
    values: Values

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password exceeds 72 UTF-8 bytes")
        return value


class Update(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    values: Values


def resolved(values):
    try:
        saved = values.model_dump()
        if saved["llm_analysis_enabled"]:
            saved["correlation_enabled"] = True
        result, locked = effective(saved)
        return saved, result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/installation/status")
def installation_status():
    done = installed(Service.document())
    if done or not Service.enabled():
        return {"installed": done, "wizard_available": False}
    values, locked = effective()
    return {"installed": False, "wizard_available": True, "defaults": values, "locked_fields": locked}


@router.post("/installation/test")
async def installation_test(values: Values, token: Optional[str] = Header(None, alias="X-TierX-Installation-Token")):
    Service.authorize_setup(token)
    _, result = resolved(values)
    return await Service.test(result)


@router.post("/installation/complete")
async def installation_complete(body: Complete, token: Optional[str] = Header(None, alias="X-TierX-Installation-Token")):
    Service.authorize_setup(token)
    saved, result = resolved(body.values)
    if result["llm_analysis_enabled"]:
        await Service.test(result)
    Service.reserve(str(body.email), body.password, validate(saved))
    return {"installed": True}


@router.get("/admin/settings/platform")
def platform_settings(admin=Depends(require_platform_admin)):
    return Service.read()


@router.put("/admin/settings/platform")
async def update_platform_settings(body: Update, admin=Depends(require_platform_admin)):
    try:
        return await Service.update(body.values.model_dump(), body.expected_revision, admin.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/admin/settings/platform/test")
async def test_platform_settings(values: Values, admin=Depends(require_platform_admin)):
    _, result = resolved(values)
    return await Service.test(result)
