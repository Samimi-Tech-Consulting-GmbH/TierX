from tierx_tools import http_request


def run(alert: AlertContext, cluster: ClusterContext | None) -> dict:
    # Explicitly approve health.example.test:443 before using this synthetic example.
    response = http_request("https://health.example.test/health")
    return {"healthy": response["status"] == 200}
