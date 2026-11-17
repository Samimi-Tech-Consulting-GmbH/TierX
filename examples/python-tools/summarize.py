def run(alert: AlertContext, cluster: ClusterContext | None) -> str:
    host = alert["normalized_payload"].get("host.name", "unknown")
    members = len(cluster["members"]) if cluster else 0
    return f"Synthetic alert {alert['alert_id']} on {host}; related snapshots: {members}."
