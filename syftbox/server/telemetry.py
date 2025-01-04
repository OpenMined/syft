from loguru import logger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from syftbox import __version__

OTEL_ATTR_CLIENT_VERSION = "syftbox.client.version"
OTEL_ATTR_CLIENT_PYTHON = "syftbox.client.python"
OTEL_ATTR_CLIENT_USER = "syftbox.client.user"
OTEL_ATTR_CLIENT_USER_LOC = "syftbox.client.user.location"
OTEL_ATTR_CLIENT_OS_NAME = "syftbox.client.os.name"
OTEL_ATTR_CLIENT_OS_VER = "syftbox.client.os.version"
OTEL_ATTR_CLIENT_OS_ARCH = "syftbox.client.os.arch"
OTEL_ATTR_SERVER_VERSION = "syftbox.server.version"


def setup_otel_exporter(env: str) -> None:
    exporter = OTLPSpanExporter()
    span_processor = BatchSpanProcessor(exporter)

    resource = Resource(
        {
            "service.name": "syftbox-server",
            "deployment.environment": env.lower(),
            OTEL_ATTR_SERVER_VERSION: __version__,
        }
    )
    resource = resource.merge(OTELResourceDetector().detect())

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)

    logger.info(f"OTEL Exporter: {exporter._endpoint}")
    logger.info(f"OTEL Resource: {tracer_provider.resource.attributes}")
