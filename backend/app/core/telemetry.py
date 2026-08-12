"""Optional OpenTelemetry setup with a no-op local default."""
import logging

from app.config import settings

logger = logging.getLogger(__name__)
_configured = False


def configure_telemetry(app) -> None:
    """Instrument FastAPI only when telemetry dependencies/configuration permit it."""
    global _configured
    if _configured:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    except ImportError:
        logger.info("OpenTelemetry packages are not installed; tracing is disabled")
        return

    try:
        provider = TracerProvider(resource=Resource.create({"service.name": "neural-rag-backend"}))
        if settings.OTEL_EXPORTER_ENDPOINT:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_ENDPOINT)))
            logger.info("OpenTelemetry exporting to configured OTLP endpoint")
        elif settings.OTEL_CONSOLE_EXPORTER:
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            logger.info("OpenTelemetry console exporter enabled")
        else:
            logger.info("OpenTelemetry running with no-op exporter (set OTEL_EXPORTER_ENDPOINT to export spans)")
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        _configured = True
    except Exception:
        # Observability must never prevent the product from booting.
        logger.exception("Could not configure OpenTelemetry; tracing is disabled")


def tracer():
    """Return a tracer even when the SDK is intentionally absent/no-op."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("neuralrag.langgraph")
    except ImportError:
        return _NoopTracer()


class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def set_attribute(self, key, value):
        return None


class _NoopTracer:
    def start_as_current_span(self, name):
        return _NoopSpan()
