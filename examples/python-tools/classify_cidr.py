import ipaddress


def run(alert: AlertContext, cluster: ClusterContext | None) -> dict:
    value = alert["normalized_payload"].get("source.ip", "192.0.2.1")
    address = ipaddress.ip_address(value)
    return {"documentation_network": address in ipaddress.ip_network("192.0.2.0/24")}
