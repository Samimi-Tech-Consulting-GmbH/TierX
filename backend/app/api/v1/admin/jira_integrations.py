from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import require_platform_admin
from app.schemas.jira_integration import (
    JiraIntegrationCreate,
    JiraIntegrationCreated,
    JiraIntegrationDocument,
    JiraProjectRouteCreate,
    JiraProjectRouteDocument,
    JiraProjectRouteStateUpdate,
    JiraProjectRouteUpdate,
)
from app.schemas.user import AuthenticatedUser
from app.services.jira_integration_service import JiraIntegrationService

router = APIRouter(prefix="/integrations/jira", tags=["Admin Jira Integrations"])


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=JiraIntegrationCreated
)
def create_jira_integration(
    body: JiraIntegrationCreate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.create_integration(body, admin.email)


@router.get("", response_model=list[JiraIntegrationDocument])
def list_jira_integrations(
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.list_integrations()


@router.get("/{integration_id}", response_model=JiraIntegrationDocument)
def get_jira_integration(
    integration_id: str,
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.get_integration(integration_id)


@router.post(
    "/{integration_id}/rotate", response_model=JiraIntegrationCreated
)
def rotate_jira_integration(
    integration_id: str,
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.rotate_secret(integration_id)


@router.delete(
    "/{integration_id}", response_model=JiraIntegrationDocument
)
def revoke_jira_integration(
    integration_id: str,
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.revoke(integration_id)


@router.get(
    "/{integration_id}/routes", response_model=list[JiraProjectRouteDocument]
)
def list_jira_project_routes(
    integration_id: str,
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.list_routes(integration_id)


@router.post(
    "/{integration_id}/routes",
    status_code=status.HTTP_201_CREATED,
    response_model=JiraProjectRouteDocument,
)
def create_jira_project_route(
    integration_id: str,
    body: JiraProjectRouteCreate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.create_route(integration_id, body, admin.email)


@router.put(
    "/{integration_id}/routes/{route_id}",
    response_model=JiraProjectRouteDocument,
)
def update_jira_project_route(
    integration_id: str,
    route_id: str,
    body: JiraProjectRouteUpdate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.update_route(
        integration_id, route_id, body, admin.email
    )


@router.patch(
    "/{integration_id}/routes/{route_id}/state",
    response_model=JiraProjectRouteDocument,
)
def set_jira_project_route_state(
    integration_id: str,
    route_id: str,
    body: JiraProjectRouteStateUpdate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return JiraIntegrationService.set_route_enabled(
        integration_id, route_id, body.enabled, admin.email
    )


@router.delete(
    "/{integration_id}/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_jira_project_route(
    integration_id: str,
    route_id: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    JiraIntegrationService.delete_route(integration_id, route_id, admin.email)
