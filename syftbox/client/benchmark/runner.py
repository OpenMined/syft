"""Benchmark class for Syft client."""

from pathlib import Path
from typing import Optional

from syftbox.client.base import BenchmarkReporter, MetricCollector
from syftbox.client.benchmark.network_metric import ServerNetworkMetricCollector
from syftbox.lib.client_config import SyftClientConfig


class SyftBenchmarkRunner:
    """Class to run the benchmark tests for the SyftBox client."""

    def __init__(
        self,
        config: SyftClientConfig,
        reporter: BenchmarkReporter,
    ):
        self.config = config
        self.reporter = reporter

    def get_collectors(self) -> dict[str, type[MetricCollector]]:
        """Get the metric collectors for the benchmark tests."""
        return {
            "network": ServerNetworkMetricCollector,
        }

    def run(self, num_runs: int, report_path: Optional[Path] = None):
        """Run the benchmark tests."""

        # Get the metric collectors
        collectors = self.get_collectors()

        # Collect all metrics
        metrics = {}
        for name, collector in collectors.items():
            collector_instance = collector(self.config)
            # TODO: run the tests in parallel
            metrics[name] = collector_instance.collect_metrics(num_runs)

        # Generate the benchmark report

        self.reporter.generate(metrics, report_path)
