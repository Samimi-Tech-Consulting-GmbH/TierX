"""Fixed private broker transport; never accepts a URL from a tool or model."""
import os
import httpx
from tierx_workflows.python_tools import PythonToolError


async def broker_request(identity, *, request=None, cancel=False):
    return await _request("/calls/" + identity, request=request, cancel=cancel)


async def validate_with_broker(definition):
    result = await _request("/validate", request=definition)
    if result.get("valid") is not True:
        raise PythonToolError("PYTHON_DEFINITION_INVALID")
    return result


async def _request(path, *, request=None, cancel=False):
    origin = os.getenv("TIERX_PYTHON_BROKER_URL", "").rstrip("/")
    token = os.getenv("TIERX_PYTHON_BROKER_TOKEN", "")
    if not origin or not token:
        raise PythonToolError("PYTHON_RUNNER_UNAVAILABLE")
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = await client.request("DELETE" if cancel else "POST" if request else "GET", origin + path,
                headers={"Authorization": "Bearer " + token}, json=request)
        if response.status_code != 200:
            code = response.json().get("error")
            if code in {"PYTHON_QUEUE_FULL", "PYTHON_REPLAY_CONFLICT", "RUNNER_ISOLATION_UNAVAILABLE",
                "PYTHON_SYNTAX_ERROR", "SYNCHRONOUS_RUN_REQUIRED", "RUN_REQUIRES_ALERT_AND_CLUSTER"}:
                raise PythonToolError(code)
            raise PythonToolError("PYTHON_RUNNER_REJECTED")
        result = response.json()
        if path != "/validate" and result.get("state") not in {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "UNCERTAIN", "CANCELLED"}:
            raise PythonToolError("PYTHON_RUNNER_PROTOCOL_ERROR")
        return result
    except PythonToolError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise PythonToolError("PYTHON_RUNNER_UNAVAILABLE") from exc


def execution_definition(row):
    return {key: row[key] for key in ("code", "name", "description", "source", "tenant_ids", "enabled",
        "output_mode", "output_schema", "timeout_seconds", "destinations") if key in row}
