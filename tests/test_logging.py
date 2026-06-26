"""
Tests for custos/logging.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from custos.logging import CUSTOSFormatter, get_logger


class TestCUSTOSFormatter:
    def _make_record(self, msg: str, level=logging.INFO, **extra):
        logger = logging.getLogger("test")
        record = logger.makeRecord("test", level, "", 0, msg, (), None)
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_output_is_valid_json(self):
        formatter = CUSTOSFormatter()
        record = self._make_record("test message")
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_required_fields_present(self):
        formatter = CUSTOSFormatter()
        record = self._make_record("test message")
        parsed = json.loads(formatter.format(record))
        for field in ["timestamp", "level", "logger", "message"]:
            assert field in parsed

    def test_extra_fields_included(self):
        formatter = CUSTOSFormatter()
        record = self._make_record("test", client_id="abc", action="allow")
        parsed = json.loads(formatter.format(record))
        assert parsed["client_id"] == "abc"
        assert parsed["action"] == "allow"

    def test_level_is_string(self):
        formatter = CUSTOSFormatter()
        record = self._make_record("test", level=logging.WARNING)
        parsed = json.loads(formatter.format(record))
        assert parsed["level"] == "warning"

    def test_trace_id_included_when_present(self):
        formatter = CUSTOSFormatter()
        record = self._make_record("test", trace_id="abc123")
        parsed = json.loads(formatter.format(record))
        assert parsed["trace_id"] == "abc123"


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_is_namespaced(self):
        logger = get_logger("test_module")
        assert logger.name.startswith("custos.")

    def test_already_namespaced_not_doubled(self):
        logger = get_logger("custos.test_module")
        assert logger.name == "custos.test_module"
