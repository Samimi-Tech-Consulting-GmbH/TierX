from tierx_tools import tcp_connect


def run(alert: AlertContext, cluster: ClusterContext | None) -> dict:
    # Explicitly approve tcp.example.test:443. This sends no application data.
    return tcp_connect("tcp.example.test", 443)
