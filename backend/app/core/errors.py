from fastapi import HTTPException, status

class TenantSuspendedError(Exception):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(f"Tenant {tenant_id} is currently suspended.")

class ResourceNotFoundError(HTTPException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

class DuplicateResourceError(HTTPException):
    def __init__(self, detail: str = "Resource already exists"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class VersionConflictError(HTTPException):
    def __init__(self, detail: str = "Version conflict"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)
