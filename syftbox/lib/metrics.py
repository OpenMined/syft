import socket
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from statistics import mean, median, stdev

import certifi
import pycurl

MAX_THREAD_POOL_SIZE = 20


def calculate_percentile(values: list[float], percentile: float) -> float:
    """
    Calculate percentile using linear interpolation between closest ranks.
    Implementation follows the C=1 method from Wikipedia's percentile article.
    """
    if not values:
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)

    # Convert percentile to a fraction between 0 and 1
    fraction = percentile / 100.0

    # Calculate the theoretical position
    position = fraction * (n - 1)

    # Find the integers below and above the position
    lower_idx = int(position)
    upper_idx = min(lower_idx + 1, n - 1)

    # Calculate weights for interpolation
    weight = position - lower_idx

    # Interpolate between the values
    return (1 - weight) * sorted_values[lower_idx] + weight * sorted_values[upper_idx]


class TCPPerfStats:
    """Measure TCP connection performance"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.previous_latency = None
        self.jitter_values = []

    def measure_tcp_connection(self) -> tuple[float, float]:
        """
        Measure TCP connection time and calculate jitter.
        Returns (latency, jitter) in milliseconds.
        """
        try:
            start_time = time.time()
            with socket.create_connection((self.host, self.port), timeout=10) as _:
                latency = (time.time() - start_time) * 1000  # Convert to ms

                # Calculate jitter
                jitter = 0
                if self.previous_latency is not None:
                    jitter = abs(latency - self.previous_latency)
                    self.jitter_values.append(jitter)

                self.previous_latency = latency
                return latency, jitter

        except socket.error:
            return -1, -1

    def get_stats(self, num_runs: int) -> dict:
        """Perform multiple TCP connections and gather statistics."""
        latencies = []
        jitters = []

        print(f"Measuring TCP performance for {self.host}:{self.port}...")

        # Use ThreadPoolExecutor for parallel connections
        with ThreadPoolExecutor(max_workers=min(num_runs, MAX_THREAD_POOL_SIZE)) as _:
            for _ in range(num_runs):
                latency, jitter = self.measure_tcp_connection()
                if latency >= 0:
                    latencies.append(latency)
                if jitter >= 0:
                    jitters.append(jitter)
                time.sleep(0.1)  # Small delay between connections

        if not latencies:
            return {}

        return self._calculate_stats(latencies, jitters, num_runs)

    def _calculate_stats(self, latencies: list[float], jitters: list[float], num_connections: int) -> dict:
        """Generate TCP performance stats from collected data."""
        stats = {
            "tcp_latency": {},
            "tcp_jitter": {"current": jitters[-1] if jitters else 0},
        }

        for metric_name, values in [("tcp_latency", latencies), ("tcp_jitter", jitters)]:
            stats[metric_name]["min"] = min(values) if values else 0
            stats[metric_name]["max"] = max(values) if values else 0
            stats[metric_name]["avg"] = mean(values) if values else 0
            stats[metric_name]["median"] = median(values) if values else 0
            stats[metric_name]["stddev"] = stdev(values) if len(values) > 1 else 0
            stats[metric_name]["p95"] = calculate_percentile(values, 95)
            stats[metric_name]["p99"] = calculate_percentile(values, 99)

        stats["connection_success_rate"] = len(latencies) / num_connections * 100

        return stats


class HTTPPerfStats:
    """Measure HTTP connection performance"""

    def __init__(self, url: str):
        self.url = url
        self.buffer = BytesIO()

    def _create_curl(self) -> pycurl.Curl:
        """Create and configure a PycURL object."""
        c = pycurl.Curl()
        for option, value in self._get_default_options().items():
            c.setopt(option, value)
        return c

    def _get_default_options(self) -> dict:
        """Get default options for PycURL object."""
        return {
            pycurl.URL: self.url,
            pycurl.WRITEDATA: self.buffer,
            pycurl.CAINFO: certifi.where(),
            pycurl.FOLLOWLOCATION: 1,
            pycurl.MAXREDIRS: 5,
            pycurl.CONNECTTIMEOUT: 30,
            pycurl.TIMEOUT: 60,
            pycurl.SSL_VERIFYPEER: 1,
            pycurl.SSL_VERIFYHOST: 2,
        }

    def __calc_server_processing_time(self, stats: dict) -> float:
        """
        Calculate actual server processing time by subtracting connection times from TTFB.
        Server Processing Time = TTFB - (DNS + TCP + SSL)
        """

        ttfb = stats["starttransfer_time"]
        dns_time = stats["dns_time"]
        tcp_time = stats["tcp_time"]
        ssl_time = stats["ssl_time"]

        server_processing = ttfb - (dns_time + tcp_time + ssl_time)
        return max(0, server_processing)  # Ensure we don't return negative values

    def _get_stats(self) -> dict:
        """HTTP performance stats using PycURL."""

        curl = self._create_curl()

        # Clear buffer before each request
        self.buffer.seek(0)
        self.buffer.truncate()

        try:
            curl.perform()

            # Standard HTTP stats
            stats = {
                "dns_time": curl.getinfo(pycurl.NAMELOOKUP_TIME) * 1000,
                "connect_time": curl.getinfo(pycurl.CONNECT_TIME) * 1000,
                "ssl_time": (curl.getinfo(pycurl.APPCONNECT_TIME) - curl.getinfo(pycurl.CONNECT_TIME)) * 1000,
                "starttransfer_time": curl.getinfo(pycurl.STARTTRANSFER_TIME) * 1000,
                "total_time": curl.getinfo(pycurl.TOTAL_TIME) * 1000,
                "size_download": curl.getinfo(pycurl.SIZE_DOWNLOAD),
                "speed_download": curl.getinfo(pycurl.SPEED_DOWNLOAD),
                "header_size": curl.getinfo(pycurl.HEADER_SIZE),
                "request_size": curl.getinfo(pycurl.REQUEST_SIZE),
                "http_code": curl.getinfo(pycurl.HTTP_CODE),
                "primary_ip": curl.getinfo(pycurl.PRIMARY_IP),
                "primary_port": curl.getinfo(pycurl.PRIMARY_PORT),
                "tcp_time": (curl.getinfo(pycurl.CONNECT_TIME) - curl.getinfo(pycurl.NAMELOOKUP_TIME)) * 1000,
                "content_transfer_time": (curl.getinfo(pycurl.TOTAL_TIME) - curl.getinfo(pycurl.STARTTRANSFER_TIME))
                * 1000,
            }
            stats["server_processing_time"] = self.__calc_server_processing_time(stats)

        except pycurl.error as e:
            stats = {}
            print(f"Error: {e}")
        finally:
            curl.close()

        return stats

    def get_stats(self, n_runs: int) -> dict:
        """Aggregate percentile stats from multiple runs."""
        print("Measuring HTTP performance for", self.url)

        all_stats = []
        for _ in range(n_runs):
            stats = self._get_stats()
            all_stats.append(stats)

        agg_stats = defaultdict(dict)

        # Aggregate stats
        cols = [
            "dns_time",
            "connect_time",
            "ssl_time",
            "starttransfer_time",
            "total_time",
            "speed_download",
            "tcp_time",
            "content_transfer_time",
            "server_processing_time",
        ]

        # Calculate percentiles for each metric
        for col in cols:
            if col not in all_stats[0]:
                continue
            values = [s[col] for s in all_stats if col in s]
            agg_stats[col]["min"] = min(values) if values else 0
            agg_stats[col]["max"] = max(values) if values else 0
            agg_stats[col]["avg"] = mean(values) if values else 0
            agg_stats[col]["median"] = median(values) if values else 0
            agg_stats[col]["stddev"] = stdev(values) if len(values) > 1 else 0
            agg_stats[col]["p95"] = calculate_percentile(values, 99)
            agg_stats[col]["p99"] = calculate_percentile(values, 99)

        return agg_stats
