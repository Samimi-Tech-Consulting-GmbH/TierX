"""Standard-library client for the per-invocation policy proxy."""
import json
import os
import urllib.request


def _call(operation, value):
    endpoint = os.environ["TIERX_JOB_PROXY"] + "/" + operation
    request = urllib.request.Request(endpoint, data=json.dumps(value).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read(70000))
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


def http_request(url, method="GET", body=None):
    """Return status, safe response headers and UTF-8 body; redirects are not followed."""
    return _call("http", {"url": url, "method": method, "body": body})


def tcp_connect(host, port):
    """Check TCP reachability without sending application data."""
    return _call("tcp", {"host": host, "port": port})
