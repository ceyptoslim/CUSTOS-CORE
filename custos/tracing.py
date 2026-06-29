"""
CUSTOS OpenTelemetry Tracing v1.1

Lightweight tracing layer for CUSTOS requests.
Each /v1/evaluate call produces a trace span containing
client_id, action, triggered_rule, and audit_record_hash.

Backends:
- Console (default): prints spans as JSON to stdout
- OTLP (production): set OTEL_EXPORTER_OTLP_ENDPOINT to export
  to Jaeger, Grafana Tempo, or Honeycomb. Closes issue #21.
- NoOp (disabled): set CUSTOS_TRACING=disabled

OTLP export requires opentelemetry packages:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc

Example:
    OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317 uvicorn main:app
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Span:
    """A single trace span."""
    name: str
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_status(self, status: str) -> None:
        self.status = status

    def end(self) -> None:
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return round((self.end_time - self.start_time) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
        }


class ConsoleExporter:
    """Exports spans as JSON to stdout. Default for dev mode."""

    def export(self, span: Span) -> None:
        print(json.dumps({"otel.span": span.to_dict()}, default=str), flush=True)


class OTLPExporter:
    """
    Exports spans to a real OTLP collector (Jaeger, Grafana Tempo, Honeycomb).
    Requires: pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
    Set OTEL_EXPORTER_OTLP_ENDPOINT env var to your collector endpoint.
    """

    def __init__(self, endpoint: str):
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create({"service.name": "custos-core"})
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer("custos")
            self._trace = trace
            self._available = True
        except ImportError:
            print(
                "WARNING: opentelemetry packages not installed. "
                "Falling back to console exporter. "
                "Run: pip install opentelemetry-sdk "
                "opentelemetry-exporter-otlp-proto-grpc",
                flush=True,
            )
            self._available = False
            self._console = ConsoleExporter()

    def export(self, span: Span) -> None:
        if not self._available:
            self._console.export(span)
            return

        with self._tracer.start_as_current_span(span.name) as otel_span:
            for key, value in span.attributes.items():
                otel_span.set_attribute(key, str(value) if value is not None else "")
            if span.status != "OK":
                otel_span.set_status(
                    self._trace.StatusCode.ERROR, span.status
                )


class NoOpExporter:
    """Discards all spans. Used when tracing is disabled."""

    def export(self, span: Span) -> None:
        pass


class Tracer:
    """
    Minimal tracer. Creates spans and exports them on finish().
    Thread-safe for use in async FastAPI handlers.
    """

    def __init__(self) -> None:
        self._exporter = self._build_exporter()

    def _build_exporter(self):
        mode = os.getenv("CUSTOS_TRACING", "console").lower()
        if mode == "disabled":
            return NoOpExporter()
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            return OTLPExporter(endpoint)
        return ConsoleExporter()

    def start_span(self, name: str) -> Span:
        return Span(name=name)

    def finish_span(self, span: Span) -> None:
        span.end()
        self._exporter.export(span)


# Module-level singleton
tracer = Tracer()
