"""Tests for SkillPoolLogger — structlog-style structured logging."""

from __future__ import annotations

import io
import json


from skillpool.utils.logger import (
    ConsoleRenderer,
    ContextVarsBinding,
    JSONRenderer,
    SkillPoolLogger,
    add_skill_context,
    add_timestamp,
    add_trace_id,
    format_json,
    get_skillpool_logger,
)


class TestContextVarsBinding:
    def test_bind_and_get(self):
        ContextVarsBinding.bind(skill_id="S09", checkpoint="L3")
        ctx = ContextVarsBinding.get()
        assert ctx["skill_id"] == "S09"
        assert ctx["checkpoint"] == "L3"
        ContextVarsBinding.unbind("skill_id", "checkpoint")

    def test_unbind_removes_key(self):
        ContextVarsBinding.bind(trace_id="abc123")
        ContextVarsBinding.unbind("trace_id")
        ctx = ContextVarsBinding.get()
        assert "trace_id" not in ctx

    def test_get_empty(self):
        ContextVarsBinding.unbind("skill_id", "checkpoint", "gate_result", "trace_id")
        ctx = ContextVarsBinding.get()
        assert ctx == {}


class TestProcessors:
    def test_add_timestamp(self):
        result = add_timestamp("test", "info", {"event": "test"})
        assert "timestamp" in result

    def test_add_timestamp_preserves_existing(self):
        result = add_timestamp("test", "info", {"event": "test", "timestamp": "fixed"})
        assert result["timestamp"] == "fixed"

    def test_add_trace_id_from_context(self):
        ContextVarsBinding.bind(trace_id="deadbeef")
        result = add_trace_id("test", "info", {"event": "test"})
        assert result.get("trace_id") == "deadbeef"
        ContextVarsBinding.unbind("trace_id")

    def test_add_trace_id_preserves_existing(self):
        result = add_trace_id("test", "info", {"event": "test", "trace_id": "existing"})
        assert result["trace_id"] == "existing"

    def test_add_skill_context(self):
        ContextVarsBinding.bind(skill_id="S09", gate_result="ALLOW")
        result = add_skill_context("test", "info", {"event": "test"})
        assert result.get("skill_id") == "S09"
        assert result.get("gate_result") == "ALLOW"
        ContextVarsBinding.unbind("skill_id", "gate_result")

    def test_format_json_passthrough(self):
        d = {"event": "test", "key": "value"}
        result = format_json("test", "info", d)
        assert result == d


class TestJSONRenderer:
    def test_render_json(self):
        renderer = JSONRenderer()
        output = renderer("test", "info", {"event": "hello", "level": "info"})
        parsed = json.loads(output)
        assert parsed["event"] == "hello"

    def test_render_with_datetime(self):
        from datetime import UTC, datetime

        renderer = JSONRenderer()
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        output = renderer("test", "info", {"event": "test", "ts": dt})
        parsed = json.loads(output)
        assert "ts" in parsed


class TestConsoleRenderer:
    def test_render_non_tty(self):
        stream = io.StringIO()
        stream.isatty = lambda: False
        renderer = ConsoleRenderer(stream=stream)
        output = renderer("test", "info", {"event": "hello", "timestamp": "2026-01-01", "level": "info"})
        assert "INFO" in output
        assert "hello" in output

    def test_render_tty(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        renderer = ConsoleRenderer(stream=stream)
        output = renderer("test", "warning", {"event": "alert", "timestamp": "2026-01-01", "key": "val"})
        assert "WARNING" in output
        assert "alert" in output

    def test_render_with_context(self):
        stream = io.StringIO()
        stream.isatty = lambda: False
        renderer = ConsoleRenderer(stream=stream)
        output = renderer("test", "error", {"event": "fail", "timestamp": "2026", "skill_id": "S09"})
        assert "skill_id=S09" in output


class TestSkillPoolLogger:
    def test_log_info(self):
        stream = io.StringIO()
        logger = SkillPoolLogger(
            name="test",
            renderer=JSONRenderer(),
        )
        # Redirect stderr
        import sys

        old_stderr = sys.stderr
        sys.stderr = stream
        logger.info("test message", key="value")
        sys.stderr = old_stderr

        output = stream.getvalue()
        parsed = json.loads(output.strip())
        assert parsed["event"] == "test message"
        assert parsed["key"] == "value"

    def test_log_levels(self):
        stream = io.StringIO()
        logger = SkillPoolLogger(name="test", renderer=JSONRenderer())
        import sys

        old_stderr = sys.stderr
        sys.stderr = stream
        for level_method in [logger.debug, logger.info, logger.warning, logger.error]:
            level_method("msg")
        sys.stderr = old_stderr

        lines = stream.getvalue().strip().split("\n")
        assert len(lines) == 4

    def test_bind_context(self):
        _stream = io.StringIO()
        logger = SkillPoolLogger(name="test", renderer=JSONRenderer())
        bound = logger.bind(skill_id="S09")
        assert bound._bound == {"skill_id": "S09"}
        assert logger._bound == {}  # Original not modified

    def test_bound_logger_includes_context(self):
        stream = io.StringIO()
        logger = SkillPoolLogger(name="test", renderer=JSONRenderer())
        bound = logger.bind(skill_id="S09")
        import sys

        old_stderr = sys.stderr
        sys.stderr = stream
        bound.info("test")
        sys.stderr = old_stderr

        parsed = json.loads(stream.getvalue().strip())
        assert parsed["skill_id"] == "S09"

    def test_kwargs_override_bound(self):
        stream = io.StringIO()
        logger = SkillPoolLogger(name="test", renderer=JSONRenderer())
        bound = logger.bind(skill_id="S09")
        import sys

        old_stderr = sys.stderr
        sys.stderr = stream
        bound.info("test", skill_id="S05a")
        sys.stderr = old_stderr

        parsed = json.loads(stream.getvalue().strip())
        assert parsed["skill_id"] == "S05a"


class TestGetSkillpoolLogger:
    def test_factory_returns_logger(self):
        logger = get_skillpool_logger("test.module")
        assert isinstance(logger, SkillPoolLogger)
        assert logger._name == "test.module"

    def test_factory_with_log_level_env(self):
        import os

        os.environ["SKILLPOOL_LOG_LEVEL"] = "DEBUG"
        logger = get_skillpool_logger("test")
        assert isinstance(logger, SkillPoolLogger)
        del os.environ["SKILLPOOL_LOG_LEVEL"]
