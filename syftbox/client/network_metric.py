from datetime import datetime
from urllib.parse import urlparse

import requests

from syftbox.client.base import MetricCollector
from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.metrics import HTTPPerfStats, TCPPerfStats


class ServerNetworkMetricCollector(MetricCollector):
    """Class for collecting network performance metrics for a server."""

    tcp_perf: TCPPerfStats
    http_perf: HTTPPerfStats

    def __init__(self, config: SyftClientConfig):
        self.client_config = config
        self.__init_perf_stats()

    @property
    def url(self) -> str:
        """URL of the server."""
        return str(self.client_config.server_url)

    def __init_perf_stats(self):
        """Initialize TCP and HTTP performance stats objects."""

        parsed = urlparse(self.url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.tcp_perf = TCPPerfStats(host, port)
        self.http_perf = HTTPPerfStats(self.url)

    def collect_metrics(self, num_runs: int) -> dict:
        """Calculate network performance metrics."""

        # Check if the server is reachable
        if not self.ping():
            return {"error": f"Server: {self.url} is not reachable."}

        print(f"Collecting metrics for {self.url}...")
        # Collect TCP performance stats
        tcp_stats = self.tcp_perf.get_stats(num_runs)

        # Collect HTTP performance stats
        http_stats = self.http_perf.get_stats(num_runs)

        network_metrics = {
            "url": self.url,
            "timestamp": datetime.now().isoformat(),
            "num_runs": num_runs,
            "stats": {"HTTP": http_stats, "TCP": tcp_stats},
        }

        return network_metrics

    def ping(self) -> bool:
        """Check if the server is reachable."""
        result = requests.get(str(self.url))
        result.raise_for_status()
        return True