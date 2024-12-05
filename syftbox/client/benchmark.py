"""Benchmark class for Syft client."""

import json
from pathlib import Path

from syftbox.client.base import MetricCollector
from syftbox.client.network_metric import ServerNetworkMetricCollector
from syftbox.lib.client_config import SyftClientConfig


class SyftBenchmark:
    """Class to run the benchmark tests for the SyftBox client."""

    def __init__(
        self,
        config: SyftClientConfig,
        report_path: Path,
    ):
        self.config = config
        self.output_path = report_path

    def get_collectors(self) -> dict[str, type[MetricCollector]]:
        """Get the metric collectors for the benchmark tests."""
        return {
            "network": ServerNetworkMetricCollector,
        }

    def run(self, num_runs: int):
        """Run the benchmark tests."""

        # Initialize the benchmark report
        benchmark_report = {}

        # Get the metric collectors
        collectors = self.get_collectors()

        # Run performance tests
        for test_name, collector in collectors.items():
            collector_instance = collector(self.config)
            # TODO: run the tests in parallel
            test_report = collector_instance.collect_metrics(num_runs)
            benchmark_report[test_name] = test_report

        # Save the benchmark report
        self.save_report(benchmark_report)

    def save_report(self, report: dict):
        """Save the benchmark report."""

        if self.output_path.is_dir():
            self.output_path.mkdir(parents=True, exist_ok=True)
        output_path = self.output_path / "benchmark_report.json"
        output_path.write_bytes(json.dumps(report, indent=4).encode())
        print("Benchmark report saved at:", output_path.resolve())


def run_benchmark(config_path: Path, report_path: Path, num_runs: int):
    """Run the SyftBox benchmark."""
    try:
        config = SyftClientConfig.load(config_path)
        benchmark = SyftBenchmark(config, report_path)
        benchmark.run(num_runs)
    except Exception as e:
        print(f"Error: {e}")
        raise e
