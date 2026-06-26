"""
Tests for custos/tracing.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import pytest
from custos.tracing import Span, Tracer


class TestSpan:
    def test_span_has_trace_id(self):
        span = Span(name="test")
        assert isinstance(span.trace_id, str)
        assert len(span.trace_id) == 32  # uuid4 hex

    def test_span_has_span_id(self):
        span = Span(name="test")
        assert isinstance(span.span_id, str)
        assert len(span.span_id) == 16

    def test_two_spans_have_different_trace_ids(self):
        span1 = Span(name="test")
        span2 = Span(name="test")
        assert span1.trace_id != span2.trace_id

    def test_set_attribute(self):
        span = Span(name="test")
        span.set_attribute("client_id", "default")
        assert span.attributes["client_id"] == "default"

    def test_end_sets_end_time(self):
        span = Span(name="test")
        assert span.end_time is None
        span.end()
        assert span.end_time is not None

    def test_duration_ms_after_end(self):
        span = Span(name="test")
        time.sleep(0.01)
        span.end()
        assert span.duration_ms >= 0

    def test_duration_ms_zero_before_end(self):
        span = Span(name="test")
        assert span.duration_ms == 0.0

    def test_to_dict_has_required_fields(self):
        span = Span(name="test")
        span.end()
        d = span.to_dict()
        for field in ["trace_id", "span_id", "name", "start_time",
                      "end_time", "duration_ms", "status", "attributes"]:
            assert field in d

    def test_set_status(self):
        span = Span(name="test")
        span.set_status("ERROR")
        assert span.status == "ERROR"


class TestTracer:
    def test_start_span_returns_span(self):
        t = Tracer()
        span = t.start_span("test.operation")
        assert isinstance(span, Span)
        assert span.name == "test.operation"

    def test_finish_span_sets_end_time(self):
        t = Tracer()
        span = t.start_span("test")
        t.finish_span(span)
        assert span.end_time is not None

    def test_trace_id_is_consistent(self):
        t = Tracer()
        span = t.start_span("test")
        trace_id = span.trace_id
        t.finish_span(span)
        assert span.trace_id == trace_id
