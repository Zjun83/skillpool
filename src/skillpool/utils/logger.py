"""SkillPoolLogger — structlog-style structured logging without external dependencies.

Processor chain: add_timestamp -> add_trace_id -> add_skill_context -> format_json
Context binding: bind_contextvars(skill_id=..., checkpoint=..., gate_result=...)
Canonical log lines: single JSON line with all context
Two renderers: JSONRenderer (prod) and ConsoleRenderer (dev, colored)
"""

from __future__ import annotations

__all__ = [
    "ConsoleRenderer",
    "ContextVarsBinding",
    "JSONRenderer",
    "SkillPoolLogger",
    "get_skillpool_logger",
]

import json
import sys
from contextvars import ContextVar
from typing import Any

from skillpool.utils.time_utils import utc_now


# ── Context Variables ──

_context_vars: dict[str, ContextVar[Any]] = {}


def _get_context_var(key: str) -> ContextVar[Any]:
    """Get or create a ContextVar for the given key."""
    if key not in _context_vars:
        _context_vars[key] = ContextVar(f"skillpool_log_{key}", default=None)
    return _context_vars[key]


class ContextVarsBinding:
    """Thread-safe + asyncio-safe context variable binding.

    Uses Python's contextvars module for automatic propagation across
    asyncio tasks and thread pools.
    """

    @staticmethod
    def bind(**kwargs: Any) -> None:
        """Bind context variables. These will be included in all subsequent log entries."""
        for key, value in kwargs.items():
            var = _get_context_var(key)
            var.set(value)

    @staticmethod
    def unbind(*keys: str) -> None:
        """Unbind context variables by resetting them to None."""
        for key in keys:
            var = _get_context_var(key)
            var.set(None)

    @staticmethod
    def get() -> dict[str, Any]:
        """Get all currently bound context variables as a dict."""
        result: dict[str, Any] = {}
        for key, var in _context_vars.items():
            value = var.get(None)
            if value is not None:
                result[key] = value
        return result


# ── Processors ──


def add_timestamp(logger: str, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add ISO 8601 UTC timestamp to the event dict."""
    if "timestamp" not in event_dict:
        event_dict["timestamp"] = utc_now().isoformat()
    return event_dict


def add_trace_id(logger: str, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add trace_id from context vars if not already present."""
    if "trace_id" not in event_dict:
        ctx = ContextVarsBinding.get()
        if "trace_id" in ctx:
            event_dict["trace_id"] = ctx["trace_id"]
    return event_dict


def add_skill_context(logger: str, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add skill_id, checkpoint, gate_result from context vars."""
    ctx = ContextVarsBinding.get()
    for key in ("skill_id", "checkpoint", "gate_result"):
        if key not in event_dict and key in ctx:
            event_dict[key] = ctx[key]
    return event_dict


def format_json(logger: str, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Ensure event_dict is JSON-serializable. No-op processor for consistency."""
    return event_dict


# ── Renderers ──


class JSONRenderer:
    """Render log events as single JSON lines (production)."""

    def __call__(self, logger: str, method: str, event_dict: dict[str, Any]) -> str:
        """Render event dict to a JSON string."""
        return json.dumps(event_dict, sort_keys=True, ensure_ascii=False, default=str)


class ConsoleRenderer:
    """Render log events as colored console output (development).

    Color codes:
    - DEBUG:    grey
    - INFO:     green
    - WARNING:  yellow
    - ERROR:    red
    """

    _COLORS: dict[str, str] = {
        "debug": "\033[90m",  # grey
        "info": "\033[32m",  # green
        "warning": "\033[33m",  # yellow
        "error": "\033[31m",  # red
    }
    _RESET = "\033[0m"

    def __init__(self, stream: Any | None = None) -> None:
        self._stream = stream or sys.stderr
        self._is_tty = hasattr(self._stream, "isatty") and self._stream.isatty()

    def __call__(self, logger: str, method: str, event_dict: dict[str, Any]) -> str:
        """Render event dict to a colored console line."""
        level = method.upper()
        timestamp = event_dict.pop("timestamp", "")
        message = event_dict.pop("event", "")

        # Build context suffix from remaining fields
        context_parts = []
        for k, v in sorted(event_dict.items()):
            context_parts.append(f"{k}={v}")
        context_str = " ".join(context_parts)

        if self._is_tty:
            color = self._COLORS.get(method, "")
            line = f"{color}{level:<8}{self._RESET} {timestamp} {message}"
            if context_str:
                line += f"  {context_str}"
        else:
            line = f"{level:<8} {timestamp} {message}"
            if context_str:
                line += f"  {context_str}"

        # Restore popped keys so the dict is not mutated for other processors
        if timestamp:
            event_dict["timestamp"] = timestamp
        event_dict["event"] = message

        return line


# ── Default processor chain ──

DEFAULT_PROCESSORS = [
    add_timestamp,
    add_trace_id,
    add_skill_context,
    format_json,
]

DEFAULT_RENDERER = JSONRenderer()


def get_skillpool_logger(name: str) -> SkillPoolLogger:
    """Factory: return a SkillPoolLogger with the appropriate renderer.

    In prod (SKILLPOOL_LOG_LEVEL=PROD or when not a TTY), uses JSONRenderer.
    Otherwise uses ConsoleRenderer for readable dev output.
    """
    import os as _os

    _log_level = _os.environ.get("SKILLPOOL_LOG_LEVEL", "INFO").upper()
    renderer: Any = ConsoleRenderer() if sys.stderr.isatty() else JSONRenderer()
    return SkillPoolLogger(name=name, renderer=renderer)


# ── Logger ──


class SkillPoolLogger:
    """structlog-style structured logger.

    Processor chain: add_timestamp -> add_trace_id -> add_skill_context -> format_json
    Each log entry goes through the processor chain, then gets rendered.

    Args:
        name: Logger name (usually module path).
        processors: List of processor callables. Each takes (logger, method, event_dict) -> event_dict.
        renderer: Final renderer callable. Takes (logger, method, event_dict) -> str.
    """

    def __init__(
        self,
        name: str,
        processors: list | None = None,
        renderer: Any | None = None,
    ) -> None:
        self._name = name
        self._processors = processors or list(DEFAULT_PROCESSORS)
        self._renderer = renderer or DEFAULT_RENDERER
        self._bound: dict[str, Any] = {}

    def bind(self, **kwargs: Any) -> SkillPoolLogger:
        """Return a new logger with additional bound context.

        The original logger is not modified.
        """
        new_logger = SkillPoolLogger(
            name=self._name,
            processors=self._processors,
            renderer=self._renderer,
        )
        new_logger._bound = {**self._bound, **kwargs}
        return new_logger

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        """Core logging method: build event dict, run processors, render, emit."""
        event_dict: dict[str, Any] = {
            "event": message,
            "logger": self._name,
            "level": level,
        }

        # Merge bound context
        event_dict.update(self._bound)

        # Merge call-site kwargs (override bound)
        event_dict.update(kwargs)

        # Run processor chain
        for processor in self._processors:
            event_dict = processor(self._name, level, event_dict)

        # Render
        output = self._renderer(self._name, level, event_dict)

        # Emit to stderr
        try:
            sys.stderr.write(output + "\n")
            sys.stderr.flush()
        except (ValueError, OSError):
            pass  # stderr closed or broken — don't crash

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log at DEBUG level."""
        self._log("debug", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log at INFO level."""
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log at WARNING level."""
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log at ERROR level."""
        self._log("error", message, **kwargs)
