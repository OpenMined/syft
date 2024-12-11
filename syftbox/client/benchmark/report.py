import json
from dataclasses import asdict
from pathlib import Path

from typing_extensions import Optional

from syftbox.client.base import BaseMetric, BenchmarkReporter
from syftbox.client.benchmark.network_metric import NetworkMetric


class JsonBenchmarkReport(BenchmarkReporter):
    """JSON format benchmark report."""

    def generate(self, metrics: dict[str, BaseMetric], report_path: Optional[Path] = None) -> dict:
        """Generate the benchmark report in JSON format."""
        report = {
            "metrics": {name: asdict(metric) for name, metric in metrics.items()},
        }

        print("Benchmark report:", json.dumps(report, indent=2))
        if report_path:
            self.save(report, report_path)

        return report

    def save(self, report: dict, output_path: Path):
        """Save the benchmark report in JSON format."""
        with open(output_path / "benchmark.json", "w") as f:
            json.dump(report, f, indent=4)

        print("Benchmark report saved to:", output_path / "benchmark.json")


class HumanReadableBenchmarkReport(BenchmarkReporter):
    """Human readable format benchmark report."""

    def generate(self, metrics: dict[str, BaseMetric], report_path: Optional[Path] = None) -> str:
        """Generate the benchmark report in human readable format."""

        sections = ["\nBenchmark Report", "=" * 16, ""]

        for name, metric in metrics.items():
            if isinstance(metric, NetworkMetric):
                sections.extend(
                    [
                        f"Network Metrics for : {metric.url}",
                        f"Timestamp: {metric.timestamp} UTC",
                        f"Number of runs: {metric.num_runs}",
                        "\nHTTP Statistics: ",
                        "--------------------",
                        f"DNS lookup time (ms): {self.dict_to_str(asdict(metric.http_stats.dns_time))}",
                        f"Connection Time (ms): {self.dict_to_str(asdict(metric.http_stats.connect_time))}",
                        f"SSL Handshake (ms): {self.dict_to_str(asdict(metric.http_stats.ssl_time))}",
                        f"TCP Time (ms): {self.dict_to_str(asdict(metric.http_stats.tcp_time))}",
                        f"Time to First Byte (ms): {self.dict_to_str(asdict(metric.http_stats.starttransfer_time))}",
                        f"Total Time (ms): {self.dict_to_str(asdict(metric.http_stats.total_time))}",
                        f"Server Processing Time (ms): {self.dict_to_str(asdict(metric.http_stats.server_processing_time))}",
                        f"Succeeded Requests: {metric.http_stats.success_rate} %",
                        "\nTCP Statistics: ",
                        "-------------------",
                        f"TCP Latency (ms): {self.dict_to_str(asdict(metric.tcp_stats.latency_stats))}",
                        f"TCP Jitter (ms): {self.dict_to_str(asdict(metric.tcp_stats.jitter_stats))}",
                        f"Connection Success Rate: {metric.tcp_stats.connection_success_rate} %",
                        "=" * 16,
                    ]
                )

        report = "\n".join(sections)
        print(report)

        if report_path:
            self.save(report, report_path)

        return report

    def dict_to_str(self, data: dict) -> str:
        """Convert dataclass to string representation."""
        return ", ".join([f"{name}: {value}" for name, value in data.items()])

    def save(self, report: str, output_path: Path):
        """Save the benchmark report in human readable format."""
        with open(output_path / "benchmark.txt", "w") as f:
            f.write(report)

        print("Benchmark report saved to:", output_path / "benchmark.txt")
