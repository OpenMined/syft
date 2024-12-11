import socket
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from statistics import mean, quantiles, stdev

from curl_cffi import Curl, CurlInfo, CurlOpt
from typing_extensions import Deque, Generator, Optional


@dataclass
class ConnectionMetadata:
    timestamp: datetime
    host: str
    port: int


@dataclass
class AggregateStats:
    """Common statistics structure."""

    min: float
    max: float
    avg: float
    median: float
    stddev: float
    p95: float
    p99: float


@dataclass
class TCPMetrics:
    """TCP performance metrics."""

    latency_stats: AggregateStats
    jitter_stats: AggregateStats
    connection_success_rate: float
    requests_per_minute: int
    max_requests_per_minute: int
    max_concurrent_connections: int
    requests_in_last_minute: int


@dataclass
class HTTPMetrics:
    """HTTP performance metrics."""

    dns_time: AggregateStats
    connect_time: AggregateStats
    ssl_time: AggregateStats
    starttransfer_time: AggregateStats
    total_time: AggregateStats
    tcp_time: AggregateStats
    content_transfer_time: AggregateStats
    server_processing_time: AggregateStats
    success_rate: float


class RateLimiter:
    """Manages connection rate limiting"""

    def __init__(self, max_requests_per_minute: int):
        self.max_requests = max_requests_per_minute
        self.requests: Deque[datetime] = deque()
        self.lock = threading.Lock()

    def _clean_old_requests(self) -> None:
        """Remove requests older than 1 minute"""
        cutoff = datetime.now() - timedelta(minutes=1)
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()

    @contextmanager
    def rate_limit(self) -> Generator[None, None, None]:
        """Context manager for rate limiting"""
        with self.lock:
            self._clean_old_requests()
            while len(self.requests) >= self.max_requests:
                time.sleep(0.1)
                self._clean_old_requests()
            self.requests.append(datetime.now())
            yield


@dataclass
class TCPConnection:
    """Handles single TCP connection measurement"""

    host: str
    port: int
    timeout: float
    previous_latency: Optional[float] = None

    def connect(self) -> tuple[float, float]:
        """Establish TCP connection and measure performance"""
        try:
            start_time = time.time()
            with socket.create_connection((self.host, self.port), timeout=self.timeout):
                latency = (time.time() - start_time) * 1000

                # Calculate jitter
                jitter = 0
                if self.previous_latency is not None:
                    jitter = abs(latency - self.previous_latency)

                return latency, jitter

        except socket.error:
            return -1, -1


class TCPPerfStats:
    """Measure TCP connection performance"""

    max_connections_per_minute: int = 30
    max_concurrent_connections: int = 3
    connection_timeout: float = 10.0
    min_delay_between_requests: float = 0.5

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.__post_init__()

    def __post_init__(self):
        self.previous_latency = None
        self.jitter_values = []
        self.request_history: Deque[ConnectionMetadata] = deque()
        self.rate_limiter = RateLimiter(self.max_connections_per_minute)
        self.connection_lock = threading.Lock()

    @contextmanager
    def _connection_context(self) -> Generator[None, None, None]:
        """Context manager for connection tracking"""
        metadata = ConnectionMetadata(datetime.now(), self.host, self.port)
        try:
            with self.connection_lock:
                self.request_history.append(metadata)
            yield
        finally:
            # Clean old history
            with self.connection_lock:
                cutoff = datetime.now() - timedelta(minutes=1)
                while self.request_history and self.request_history[0].timestamp < cutoff:
                    self.request_history.popleft()

    def measure_single_connection(self) -> tuple[float, float]:
        """Measure a single TCP connection with rate limiting"""
        with self.rate_limiter.rate_limit():
            with self._connection_context():
                conn = TCPConnection(self.host, self.port, self.connection_timeout, self.previous_latency)
                latency, jitter = conn.connect()

                if latency >= 0:
                    self.previous_latency = latency
                    if jitter >= 0:
                        self.jitter_values.append(jitter)

                time.sleep(self.min_delay_between_requests)
                return latency, jitter

    def get_stats(self, num_runs: int) -> dict:
        """Perform multiple TCP connections and gather statistics."""
        latencies = []
        jitters = []

        print(f"Measuring TCP performance for {self.host}:{self.port}...")

        # Use ThreadPoolExecutor for parallel connections
        with ThreadPoolExecutor(max_workers=self.max_concurrent_connections) as executor:
            futures = [executor.submit(self.measure_single_connection) for _ in range(num_runs)]

            for future in futures:
                try:
                    latency, jitter = future.result()
                    if latency >= 0:
                        latencies.append(latency)
                    if jitter >= 0:
                        jitters.append(jitter)
                except Exception as e:
                    print(f"Connection error: {e}")

        if not latencies:
            return {}

        return TCPMetrics(
            latency_stats=self._calculate_stats(latencies),
            jitter_stats=self._calculate_stats(jitters),
            connection_success_rate=len(latencies) / num_runs * 100,
            requests_per_minute=len(self.request_history),
            max_requests_per_minute=self.max_connections_per_minute,
            max_concurrent_connections=self.max_concurrent_connections,
            requests_in_last_minute=len(self.request_history),
        )

    def _calculate_stats(self, values: list[float]) -> AggregateStats:
        if not values:
            return AggregateStats(0, 0, 0, 0, 0, 0, 0)

        quants = quantiles(values, n=100)
        return AggregateStats(
            min=round(min(values), 2),
            max=round(max(values), 2),
            avg=round(mean(values), 2),
            median=round(quants[49], 2),  # median
            stddev=round(stdev(values), 2) if len(values) > 1 else 0,
            p95=round(quants[94], 2),  # 95th percentile
            p99=round(quants[98], 2),  # 99th percentile
        )


@dataclass
class HTTPStats:
    """Container for HTTP timing statistics"""

    dns_time: float = 0.0
    connect_time: float = 0.0
    ssl_time: float = 0.0
    starttransfer_time: float = 0.0
    total_time: float = 0.0
    header_size: int = 0
    request_size: int = 0
    http_code: int = 0
    primary_ip: str = ""
    primary_port: int = 0
    tcp_time: float = 0.0
    content_transfer_time: float = 0.0
    server_processing_time: float = 0.0


class HTTPPerfStats:
    """Measure HTTP connection performance using curl_cffi"""

    def __init__(self, url: str):
        self.url = url
        self.buffer: BytesIO = BytesIO()
        self.connect_timeout: int = 30
        self.total_timeout: int = 60
        self.max_redirects: int = 5

    def _get_default_options(self) -> dict[CurlOpt, any]:
        """Get default options for curl_cffi"""
        return {
            CurlOpt.URL: self.url.encode(),
            CurlOpt.WRITEDATA: self.buffer,
            CurlOpt.FOLLOWLOCATION: 1,
            CurlOpt.MAXREDIRS: self.max_redirects,
            CurlOpt.CONNECTTIMEOUT: self.connect_timeout,
            CurlOpt.TIMEOUT: self.total_timeout,
            CurlOpt.SSL_VERIFYPEER: 1,
            CurlOpt.SSL_VERIFYHOST: 2,
        }

    @contextmanager
    def _create_curl(self):
        """Context manager for curl_cffi handle"""
        curl = Curl()
        try:
            for option, value in self._get_default_options().items():
                curl.setopt(option, value)
            yield curl
        finally:
            curl.close()

    def _calc_server_processing_time(self, stats: HTTPStats) -> float:
        """
        Calculate actual server processing time by subtracting connection times from TTFB.
        Server Processing Time = TTFB - (DNS + TCP + SSL)
        """
        server_processing = stats.starttransfer_time - (stats.dns_time + stats.tcp_time + stats.ssl_time)
        return max(0, server_processing)

    def _get_stats(self) -> Optional[HTTPStats]:
        """Get HTTP performance stats for a single request"""
        self.buffer.seek(0)
        self.buffer.truncate()

        with self._create_curl() as curl:
            try:
                curl.perform()

                # Convert times to milliseconds
                stats = HTTPStats(
                    dns_time=curl.getinfo(CurlInfo.NAMELOOKUP_TIME) * 1000,
                    connect_time=curl.getinfo(CurlInfo.CONNECT_TIME) * 1000,
                    ssl_time=(curl.getinfo(CurlInfo.APPCONNECT_TIME) - curl.getinfo(CurlInfo.CONNECT_TIME)) * 1000,
                    starttransfer_time=curl.getinfo(CurlInfo.STARTTRANSFER_TIME) * 1000,
                    total_time=curl.getinfo(CurlInfo.TOTAL_TIME) * 1000,
                    header_size=curl.getinfo(CurlInfo.HEADER_SIZE),
                    request_size=curl.getinfo(CurlInfo.REQUEST_SIZE),
                    http_code=curl.getinfo(CurlInfo.RESPONSE_CODE),
                    primary_ip=curl.getinfo(CurlInfo.PRIMARY_IP),
                    primary_port=curl.getinfo(CurlInfo.PRIMARY_PORT),
                    tcp_time=(curl.getinfo(CurlInfo.CONNECT_TIME) - curl.getinfo(CurlInfo.NAMELOOKUP_TIME)) * 1000,
                    content_transfer_time=(
                        curl.getinfo(CurlInfo.TOTAL_TIME) - curl.getinfo(CurlInfo.STARTTRANSFER_TIME)
                    )
                    * 1000,
                )

                stats.server_processing_time = self._calc_server_processing_time(stats)
                return stats

            except Exception as e:
                print(f"Error during request: {e}")
                return None

    def get_stats(self, n_runs: int) -> HTTPMetrics:
        """Aggregate performance stats from multiple runs"""
        print(f"Measuring HTTP performance for {self.url}")

        measurements: list[HTTPStats] = []
        for _ in range(n_runs):
            if stats := self._get_stats():
                measurements.append(stats)
            time.sleep(0.1)  # Small delay between requests

        if not measurements:
            return {}

        # Metrics to analyze
        metrics = [
            "dns_time",
            "connect_time",
            "ssl_time",
            "starttransfer_time",
            "total_time",
            "tcp_time",
            "content_transfer_time",
            "server_processing_time",
        ]

        # Calculate aggregated stats
        agg_stats = {}
        for metric in metrics:
            values = [getattr(m, metric) for m in measurements]
            agg_stats[metric] = self._calculate_stats(values)

        return HTTPMetrics(
            dns_time=agg_stats["dns_time"],
            connect_time=agg_stats["connect_time"],
            ssl_time=agg_stats["ssl_time"],
            starttransfer_time=agg_stats["starttransfer_time"],
            total_time=agg_stats["total_time"],
            tcp_time=agg_stats["tcp_time"],
            content_transfer_time=agg_stats["content_transfer_time"],
            server_processing_time=agg_stats["server_processing_time"],
            success_rate=len(measurements) / n_runs * 100,
        )

    def _calculate_stats(self, values: list[float]) -> AggregateStats:
        if not values:
            return AggregateStats(0, 0, 0, 0, 0, 0, 0)

        quants = quantiles(values, n=100)
        return AggregateStats(
            min=round(min(values), 2),
            max=round(max(values), 2),
            avg=round(mean(values), 2),
            median=round(quants[49], 2),  # median
            stddev=round(stdev(values), 2) if len(values) > 1 else 0,
            p95=round(quants[94], 2),  # 95th percentile
            p99=round(quants[98], 2),  # 99th percentile
        )
