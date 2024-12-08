import os
import platform

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def instrument_otel_trace_exporter():
    traces_endpoint = os.getenv(
        key="OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",  # TODO: set it to "https://metrics.openmined.org/v1/traces"
    )
    # Step 1: Configure the OTLP Exporter
    exporter = OTLPSpanExporter(endpoint=traces_endpoint)

    # Step 2: Set up a Tracer Provider and Span Processor
    hostname: str = platform.node()
    service_name = os.getenv("OTEL_SERVICE_NAME", f"{hostname}-syftbox-server")
    tracer_provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    span_processor = BatchSpanProcessor(exporter)
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)

    # Step 3: Create a Tracer
    # tracer = trace.get_tracer(__name__)
