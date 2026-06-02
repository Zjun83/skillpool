"""Runtime Audit Hook — Security monitoring via sys.addaudithook (PEP 578).

Tracks security-sensitive operations: exec, compile, open, subprocess.Popen,
socket.connect. Cannot be removed once registered (by design).
"""
from __future__ import annotations

__all__ = [
    "RuntimeAuditHook",
]

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


from skillpool.config import get_data_dir

_DEFAULT_LOG_DIR = get_data_dir() / "logs"
_DEFAULT_LOG_FILE = _DEFAULT_LOG_DIR / "runtime_audit.jsonl"


class RuntimeAuditHook:
    """Monitor security-sensitive operations via sys.addaudithook.

    Tracks: exec, compile, open, subprocess.Popen, socket.connect.
    Cannot be removed once registered (by design — PEP 578 constraint).

    Usage:
        hook = RuntimeAuditHook()
        hook.install()
        # ... code runs, events are logged ...
        events = hook.get_events()
    """

    MONITORED_EVENTS: frozenset[str] = frozenset({
        "exec",
        "compile",
        "open",
        "subprocess.Popen",
        "socket.connect",
    })

    def __init__(
        self,
        callback: Callable[[str, tuple[Any, ...]], None] | None = None,
        log_file: Path | None = None,
    ) -> None:
        """Initialize the audit hook.

        Args:
            callback: Optional custom callback receiving (event_name, args).
                      If None, events are logged to the default JSONL file.
            log_file: Override the default log file path.
        """
        self._callback = callback
        self._log_file = log_file or _DEFAULT_LOG_FILE
        self._installed = False
        self._events: list[dict[str, Any]] = []
        self._in_handler = False  # Reentrancy guard

    def install(self, force: bool = False) -> None:
        """Register the audit hook via sys.addaudithook.

        Safe to call multiple times — subsequent calls are no-ops.
        The hook cannot be removed once registered (PEP 578 design).

        By default, only installs in production environments
        (SKILLPOOL_ENV=prod). In dev/test, the I/O overhead of
        monitoring every open/exec/subprocess event is prohibitive.
        Use force=True to override this check.

        Args:
            force: Install regardless of environment (for tests).
        """
        if self._installed:
            return

        # Skip in non-production environments unless forced
        env = os.environ.get("SKILLPOOL_ENV", "dev")
        if env != "prod" and not force:
            self._installed = True  # Mark as installed to prevent retries
            return
        if self._installed:
            return

        def _audit_handler(event_name: str, args: tuple[Any, ...]) -> None:
            if event_name not in self.MONITORED_EVENTS:
                return

            # Reentrancy guard: prevent infinite recursion when
            # _log_to_file triggers its own 'open' audit event
            if self._in_handler:
                return
            self._in_handler = True

            try:
                entry = {
                    "event": event_name,
                    "args": _serialize_args(args),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                self._events.append(entry)

                if self._callback:
                    self._callback(event_name, args)
                else:
                    self._log_to_file(entry)
            finally:
                self._in_handler = False

        sys.addaudithook(_audit_handler)
        self._installed = True

    def get_events(self) -> list[dict[str, Any]]:
        """Retrieve all logged events since hook installation.

        Returns:
            List of event dicts with keys: event, args, timestamp.
        """
        return list(self._events)

    def is_installed(self) -> bool:
        """Check if the audit hook has been registered."""
        return self._installed

    def _log_to_file(self, entry: dict[str, Any]) -> None:
        """Append an event entry to the JSONL log file."""
        try:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            # Silently fail — audit hook must not raise (PEP 578 constraint)
            pass


def _serialize_args(args: tuple[Any, ...]) -> list[Any]:
    """Convert audit hook args to JSON-serializable form.

    Args may contain arbitrary objects; we convert what we can and
    stringify the rest.
    """
    result: list[Any] = []
    for arg in args:
        if isinstance(arg, (str, int, float, bool, type(None))):
            result.append(arg)
        elif isinstance(arg, bytes):
            result.append(arg.decode("utf-8", errors="replace"))
        elif isinstance(arg, (list, tuple, set, frozenset)):
            result.append(_serialize_args(tuple(arg)))
        elif isinstance(arg, dict):
            result.append({str(k): str(v) for k, v in arg.items()})
        else:
            result.append(str(arg))
    return result
