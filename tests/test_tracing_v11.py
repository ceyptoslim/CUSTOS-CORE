"""
Tests for custos/tracing.py v1.1 — issue #21
OTLP export and backend selection.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from custos.tracing import (
    ConsoleExporter,
    NoOpExporter,
    OTLPExporter,
    Span,
    Tracer,
)


class TestOTLPExporter:
    def test_falls_back_to_console_without_otel_packages(self, capsys):
        """
        If opentelemetry packages are not installed, OTLPExporter
        should fall back to console output gracefully.
        """
        import unittest.mock as mock
        with mock.patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.trace": None,
            "opentelemetry.sdk.trace.export": None,
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
            "opentelemetry.sdk.resources": None,
        }):
            exporter = OTLPExporter("http://localhost:4317")
            assert exporter._available is False

    def test_fallback_exports_to_console(self, capsys):
        import unittest.mock as mock
        with mock.patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.trace": None,
            "opentelemetry.sdk.trace.export": None,
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
            "opentelemetry.sdk.resources": None,
        }):
            exporter = OTLPExporter("http://localhost:4317")
            span = Span(name="test")
            span.end()
            exporter.export(span)
            captured = capsys.readouterr()
            assert "otel.span" in captured.out


class TestTracerBackendSelection:
    def test_default_is_console(self, monkeypatch):
        monkeypatch.delenv("CUSTOS_TRACING", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        t = Tracer()
        assert isinstance(t._exporter, ConsoleExporter)

    def test_disabled_mode_is_noop(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_TRACING", "disabled")
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        t = Tracer()
        assert isinstance(t._exporter, NoOpExporter)

    def test_otlp_endpoint_selects_otlp_exporter(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
        monkeypatch.delenv("CUSTOS_TRACING", raising=False)
        t = Tracer()
        assert isinstance(t._exporter, OTLPExporter)

    def test_otlp_takes_priority_over_console(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo:4317")
        monkeypatch.setenv("CUSTOS_TRACING", "console")
        t = Tracer()
        assert isinstance(t._exporter, OTLPExporter)

    def test_disabled_beats_otlp_endpoint(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_TRACING", "disabled")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
        t = Tracer()
        assert isinstance(t._exporter, NoOpExporter)


class TestSpanAttributes:
    def test_span_exports_all_attributes(self, capsys):
        exporter = ConsoleExporter()
        span = Span(name="custos.evaluate")
        span.set_attribute("client_id", "default")
        span.set_attribute("tenant_id", "acme")
        span.set_attribute("action", "deny")
        span.end()
        exporter.export(span)
        captured = capsys.readouterr()
        assert "client_id" in captured.out
        assert "acme" in captured.out
        assert "deny" in captured.out

    def test_noop_exporter_produces_no_output(self, capsys):
        exporter = NoOpExporter()
        span = Span(name="test")
        span.end()
        exporter.export(span)
        captured = capsys.readouterr()
        assert captured.out == ""
