import asyncio
import json
import statistics
import time
import uuid
from typing import Awaitable, Callable, Dict, Optional

import nats
from loguru import logger
from nats.aio.msg import Msg

# {
#     pub: requests.{me}.>
#     sub: requests.*.{me}.>, responses.{me}.>
# }
# 1. setup auth + claims
# 2. TLS
# 3. make sync wrapper that works in notebook


def email_to_nats_subject(email: str) -> str:
    return email.replace(".", ":").replace(" ", "-").replace("*", "+").replace(">", "}")


def nats_subject_to_email(segment: str) -> str:
    return segment.replace(":", ".").replace("-", " ").replace("+", "*").replace("}", ">")


def _is_wildcard(segment: str) -> bool:
    return segment == "*" or segment == ">"


def make_request_subject(requester: str, responder: str, app_name: str) -> str:
    if not _is_wildcard(requester):
        requester = email_to_nats_subject(requester)
    if not _is_wildcard(responder):
        responder = email_to_nats_subject(responder)
    return f"requests.{requester}.{responder}.{app_name}"


def parse_subject(subject: str) -> tuple:
    split = subject.split(".")
    for i, s in enumerate(split):
        if not _is_wildcard(s):
            split[i] = nats_subject_to_email(s)
    return tuple(split)


def make_response_subject(requester: str, responder: str, app_name: str, request_id: str | uuid.UUID) -> str:
    requester = email_to_nats_subject(requester)
    responder = email_to_nats_subject(responder)
    return f"responses.{requester}.{responder}.{app_name}.{request_id}"


class NatsClient:
    def __init__(self, nats_url="nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc = None
        self.js = None
        self.loop = asyncio.get_event_loop()

    async def connect(self):
        if not self.nc:
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            try:
                await self.js.add_stream(name="requests", subjects=["requests.>"])
                await self.js.add_stream(name="responses", subjects=["responses.>"])
                logger.debug("JetStream streams created")
            except Exception:
                pass

    async def publish(
        self,
        subject: str,
        payload: bytes,
        headers: Dict[str, str] | None = None,
    ):
        await self.connect()
        await self.js.publish(subject, payload, headers=headers, timeout=30)

    async def subscribe_with_callback(self, subject: str, callback: Callable):
        await self.connect()
        await self.js.subscribe(subject, cb=callback, durable="default")

    async def subscribe_iter(self, subject: str):
        await self.connect()
        async for msg in self.js.subscribe(subject, durable="default"):
            yield msg

    async def wait_for_message(self, subject: str, timeout: float = 10.0, ack: bool = True) -> Optional[bytes]:
        await self.connect()

        try:
            sub = await self.js.pull_subscribe(subject, f"temp-sub-{uuid.uuid4()}")
            msgs = await sub.fetch(1, timeout=timeout)

            if msgs:
                msg = msgs[0]
                data = msg.data
                if ack:
                    await msg.ack()
                return data
            return None
        except nats.errors.TimeoutError:
            return None

    async def close(self):
        if self.nc:
            await self.nc.close()


class NatsRPCClient(NatsClient):
    def __init__(
        self,
        requester: str,
        responder: str,
        app_name: str,
        nats_url="nats://localhost:4222",
    ):
        super().__init__(nats_url)
        self.requester = requester
        self.responder = responder
        self.app_name = app_name

    async def send_request(
        self,
        payload: bytes,
    ) -> str:
        """Send a request and return the request ID"""
        await self.connect()
        request_id = str(uuid.uuid4())
        subject = make_request_subject(self.requester, self.responder, self.app_name)
        headers = {
            "request_id": request_id,
        }

        logger.debug(f"Sending request with request_id {request_id}")
        await self.publish(subject, payload, headers=headers)
        return request_id

    async def wait_for_response(
        self,
        request_id: str,
        timeout: float = 10.0,
    ) -> Optional[bytes]:
        """Wait for a response to a specific request"""
        await self.connect()
        subject = make_response_subject(self.requester, self.responder, self.app_name, request_id)
        logger.debug(f"{self.requester} waiting for response with request_id {request_id}")
        return await self.wait_for_message(subject, timeout=timeout)


class NatsRPCServer(NatsClient):
    def __init__(
        self,
        responder: str,
        app_name: str,
        event_handler: Callable[[Msg], bytes] | Callable[[Msg], Awaitable[bytes]],
        nats_url="nats://localhost:4222",
    ):
        super().__init__(nats_url)
        self.responder = responder
        self.app_name = app_name
        self.event_handler = event_handler

    async def _event_handler(self, msg: Msg):
        try:
            await msg.ack()
            print("Received message 1")
            # Extract important information
            request_id = msg.headers.get("request_id") if msg.headers else None
            if not request_id:
                logger.error("Received request without request_id header")
                return

            # Parse the subject to get the requester
            parts = msg.subject.split(".")
            if len(parts) >= 3:  # requests.<requester>.<receiver>.<app_name>
                requester = nats_subject_to_email(parts[1])
            else:
                logger.error(f"Invalid subject format: {msg.subject}")
                return

            # Call the user-provided handler
            if asyncio.iscoroutinefunction(self.event_handler):
                response_payload = await self.event_handler(msg)
            else:
                response_payload = self.event_handler(msg)

            # Send the response if the handler returned something
            if response_payload is not None:
                await self.send_response(requester, request_id, response_payload)

        except Exception as e:
            logger.exception(f"Error handling request: {e}")

    async def send_response(self, requester: str, request_id: str, payload: bytes):
        await self.connect()
        subject = make_response_subject(requester, self.responder, self.app_name, request_id)
        headers = {
            "request_id": request_id,
        }
        logger.debug(f"Sending response to {requester} with request_id {request_id}")
        await self.publish(subject, payload, headers=headers)

    async def start(self):
        await self.connect()

        subj = make_request_subject("*", self.responder, self.app_name)
        logger.debug(f"Subscribing to {subj}")
        await self.subscribe_with_callback(subj, self._event_handler)


# Simple ping handler
def request_handler(msg: Msg) -> bytes:
    subj = parse_subject(msg.subject)
    if len(subj) != 4 or subj[0] != "requests":
        return b"Invalid subject format"

    requester = subj[1]
    responder = subj[2]
    app_name = subj[3]

    print(f"{responder} received request from {requester} for app {app_name}")
    return b"pong"


async def main():
    server = NatsRPCServer(responder="pong@example.com", app_name="pingpong", event_handler=request_handler)
    await server.start()
    print("Server started")

    client = NatsRPCClient(requester="ping@example.com", responder="pong@example.com", app_name="pingpong")

    print("Sending ping...")
    request_id = await client.send_request(b"ping")
    await asyncio.sleep(1)

    await asyncio.sleep(1)

    response = await client.wait_for_response(request_id)

    if response:
        print(f"Received: {response.decode()}")
    else:
        print("No response received (timeout)")

    # Clean up
    await client.close()
    await server.close()


# Echo handler for the server
def echo_handler(msg):
    return msg.data


async def run_benchmark():
    # Initialize server
    server = NatsRPCServer(responder="benchmark@example.com", app_name="benchmark", event_handler=echo_handler)
    await server.start()
    print("Benchmark server started")

    # Initialize client
    client = NatsRPCClient(requester="client@example.com", responder="benchmark@example.com", app_name="benchmark")

    # Parameters
    message_sizes = [10, 1_000, 10_000, 100_000, 1_000_000]  # bytes
    iterations = 100

    results = {}

    for size in message_sizes:
        print(f"\nTesting with message size: {size} bytes")
        payload = b"x" * size

        # Warmup
        for _ in range(5):
            req_id = await client.send_request(payload)
            await client.wait_for_response(req_id)

        # Measure request-response latency
        latencies = []
        for i in range(iterations):
            start_time = time.time()
            req_id = await client.send_request(payload)
            response = await client.wait_for_response(req_id)
            end_time = time.time()

            if response:
                latency = (end_time - start_time) * 1000  # ms
                latencies.append(latency)

            if i % 10 == 0:
                print(f"Completed {i}/{iterations} iterations")

        # Calculate statistics
        avg_latency = statistics.mean(latencies)
        p95_latency = sorted(latencies)[int(iterations * 0.95)]
        p99_latency = sorted(latencies)[int(iterations * 0.99)]

        throughput = iterations / sum(latencies) * 1000  # requests per second

        results[size] = {
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "p99_latency_ms": p99_latency,
            "throughput_rps": throughput,
        }

        print(f"Average latency: {avg_latency:.2f} ms")
        print(f"P95 latency: {p95_latency:.2f} ms")
        print(f"P99 latency: {p99_latency:.2f} ms")
        print(f"Throughput: {throughput:.2f} requests/second")

    print("\nBenchmark Results:")
    print(json.dumps(results, indent=2))

    # Clean up
    await client.close()
    await server.close()


# if __name__ == "__main__":
# asyncio.run(run_benchmark())

if __name__ == "__main__":
    asyncio.run(main())
