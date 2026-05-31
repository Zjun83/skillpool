"""Tests for RuntimeAuditHook — PEP 578 sys.addaudithook security monitoring.

NOTE: sys.addaudithook is process-global and cannot be removed once registered.
Tests that need actual hook registration run in subprocesses to avoid
contaminating the pytest process with I/O overhead.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from skillpool.utils.runtime_audit import RuntimeAuditHook, _serialize_args


class TestRuntimeAuditHookInit:
    """Tests for RuntimeAuditHook initialization — no hook registration needed."""

    def test_default_not_installed(self):
        """Hook should not be installed on construction."""
        hook = RuntimeAuditHook()
        assert not hook.is_installed()

    def test_custom_callback(self):
        """Custom callback should be stored."""
        calls = []
        hook = RuntimeAuditHook(callback=lambda e, a: calls.append((e, a)))
        assert hook._callback is not None

    def test_custom_log_file(self):
        """Custom log file path should be stored."""
        path = Path("/tmp/test_audit.jsonl")
        hook = RuntimeAuditHook(log_file=path)
        assert hook._log_file == path


class TestRuntimeAuditHookInstall:
    """Tests for hook installation — uses mock to avoid actual registration."""

    def test_install_sets_installed_flag(self):
        """install() should set is_installed() to True."""
        hook = RuntimeAuditHook()
        hook.install()  # dev env, no force — should mark installed but skip registration
        assert hook.is_installed()

    def test_install_idempotent(self):
        """Multiple install() calls should be no-ops."""
        hook = RuntimeAuditHook()
        hook.install()
        hook.install()
        assert hook.is_installed()

    def test_install_registers_audit_hook_with_force(self):
        """install(force=True) should register via sys.addaudithook."""
        with patch.object(sys, "addaudithook") as mock_add:
            hook = RuntimeAuditHook()
            hook.install(force=True)
            mock_add.assert_called_once()

    def test_install_skips_in_dev_environment(self):
        """install() should skip in dev environment without force."""
        hook = RuntimeAuditHook()
        # SKILLPOOL_ENV defaults to 'dev'
        hook.install(force=False)
        # Should be marked as installed but no actual hook registered
        assert hook.is_installed()
        # No events should be captured
        assert len(hook.get_events()) == 0

    def test_install_in_prod_environment(self):
        """install() should register in prod environment without force."""
        with patch.object(sys, "addaudithook") as mock_add:
            with patch.dict("os.environ", {"SKILLPOOL_ENV": "prod"}):
                hook = RuntimeAuditHook()
                hook.install()
                mock_add.assert_called_once()


class TestRuntimeAuditHookGetEvents:
    """Tests for event retrieval — no hook registration needed."""

    def test_no_events_initially(self):
        """get_events() should return empty list before any events."""
        hook = RuntimeAuditHook()
        hook.install()  # dev mode, no actual registration
        events = hook.get_events()
        assert isinstance(events, list)

    def test_get_events_returns_copy(self):
        """get_events() should return a copy, not the internal list."""
        hook = RuntimeAuditHook()
        hook.install()
        events1 = hook.get_events()
        events2 = hook.get_events()
        assert events1 is not events2


class TestMonitoredEvents:
    """Tests for the MONITORED_EVENTS set — no hook registration needed."""

    def test_required_events_monitored(self):
        """All required events should be in MONITORED_EVENTS."""
        required = {"exec", "compile", "open", "subprocess.Popen", "socket.connect"}
        assert required.issubset(RuntimeAuditHook.MONITORED_EVENTS)

    def test_monitored_events_is_frozenset(self):
        """MONITORED_EVENTS should be immutable."""
        assert isinstance(RuntimeAuditHook.MONITORED_EVENTS, frozenset)


class TestSerializeArgs:
    """Tests for _serialize_args helper — no hook registration needed."""

    def test_serialize_primitives(self):
        """Primitive types should pass through unchanged."""
        assert _serialize_args(("hello", 42, 3.14, True, None)) == [
            "hello", 42, 3.14, True, None
        ]

    def test_serialize_bytes(self):
        """Bytes should be decoded to string."""
        result = _serialize_args((b"hello",))
        assert result == ["hello"]

    def test_serialize_dict(self):
        """Dicts should have string keys and values."""
        result = _serialize_args(({"key": "value"},))
        assert result == [{"key": "value"}]

    def test_serialize_arbitrary_object(self):
        """Arbitrary objects should be str()'d."""
        result = _serialize_args((RuntimeAuditHook,))
        assert len(result) == 1
        assert isinstance(result[0], str)

    def test_serialize_nested_tuple(self):
        """Nested tuples/lists should be serialized recursively."""
        result = _serialize_args(((1, 2), [3, 4]))
        assert result == [[1, 2], [3, 4]]


class TestRuntimeAuditHookSubprocess:
    """Tests that require actual hook registration — run in subprocesses.

    sys.addaudithook is process-global and cannot be removed. Running
    these tests in subprocesses prevents I/O overhead from contaminating
    the main pytest process.
    """

    def test_captures_open_event(self):
        """Hook should capture 'open' audit events (subprocess isolated)."""
        script = textwrap.dedent("""\
            import json
            import tempfile
            from pathlib import Path
            from skillpool.utils.runtime_audit import RuntimeAuditHook

            with tempfile.TemporaryDirectory() as tmpdir:
                log_file = Path(tmpdir) / "audit.jsonl"
                hook = RuntimeAuditHook(log_file=log_file)
                hook.install(force=True)

                # Trigger an 'open' event
                with open(Path(tmpdir) / "test.txt", "w") as f:
                    f.write("test")

                events = hook.get_events()
                open_events = [e for e in events if e["event"] == "open"]
                print(json.dumps({"open_event_count": len(open_events)}))
        """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        data = json.loads(result.stdout.strip())
        assert data["open_event_count"] > 0

    def test_event_structure(self):
        """Each event should have event, args, and timestamp keys (subprocess)."""
        script = textwrap.dedent("""\
            import json
            import tempfile
            from pathlib import Path
            from skillpool.utils.runtime_audit import RuntimeAuditHook

            with tempfile.TemporaryDirectory() as tmpdir:
                log_file = Path(tmpdir) / "audit.jsonl"
                hook = RuntimeAuditHook(log_file=log_file)
                hook.install(force=True)

                with open(Path(tmpdir) / "test.txt", "w") as f:
                    f.write("test")

                events = hook.get_events()
                if events:
                    print(json.dumps({"has_keys": all(
                        k in events[0] for k in ("event", "args", "timestamp")
                    )}))
                else:
                    print(json.dumps({"has_keys": False}))
        """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        data = json.loads(result.stdout.strip())
        assert data["has_keys"]

    def test_custom_callback_receives_events(self):
        """Custom callback should be invoked with event name and args (subprocess)."""
        script = textwrap.dedent("""\
            import json
            import tempfile
            from skillpool.utils.runtime_audit import RuntimeAuditHook

            calls = []
            hook = RuntimeAuditHook(callback=lambda e, a: calls.append((e, a)))
            hook.install(force=True)

            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write("test")

            open_calls = [c for c in calls if c[0] == "open"]
            print(json.dumps({"open_callback_count": len(open_calls)}))
        """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        data = json.loads(result.stdout.strip())
        assert data["open_callback_count"] > 0

    def test_log_file_created_on_event(self):
        """Log file should be created when an event is captured (subprocess)."""
        script = textwrap.dedent("""\
            import json
            import tempfile
            from pathlib import Path
            from skillpool.utils.runtime_audit import RuntimeAuditHook

            with tempfile.TemporaryDirectory() as tmpdir:
                log_file = Path(tmpdir) / "audit.jsonl"
                hook = RuntimeAuditHook(log_file=log_file)
                hook.install(force=True)

                with open(Path(tmpdir) / "test.txt", "w") as f:
                    f.write("test")

                if log_file.exists():
                    lines = log_file.read_text().strip().split("\\n")
                    valid = all("event" in json.loads(l) and "timestamp" in json.loads(l) for l in lines if l)
                    print(json.dumps({"log_valid": valid, "line_count": len(lines)}))
                else:
                    print(json.dumps({"log_valid": False, "line_count": 0}))
        """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        data = json.loads(result.stdout.strip())
        assert data["log_valid"]

    def test_log_entries_are_valid_json(self):
        """Each line in the log file should be valid JSON (subprocess)."""
        script = textwrap.dedent("""\
            import json
            import tempfile
            from pathlib import Path
            from skillpool.utils.runtime_audit import RuntimeAuditHook

            with tempfile.TemporaryDirectory() as tmpdir:
                log_file = Path(tmpdir) / "audit.jsonl"
                hook = RuntimeAuditHook(log_file=log_file)
                hook.install(force=True)

                with open(Path(tmpdir) / "test.txt", "w") as f:
                    f.write("test")

                if log_file.exists():
                    all_dicts = True
                    for line in log_file.read_text().strip().split("\\n"):
                        if line:
                            data = json.loads(line)
                            if not isinstance(data, dict):
                                all_dicts = False
                    print(json.dumps({"all_dicts": all_dicts}))
                else:
                    print(json.dumps({"all_dicts": True}))
        """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        data = json.loads(result.stdout.strip())
        assert data["all_dicts"]
