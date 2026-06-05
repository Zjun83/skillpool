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
        assert _serialize_args(("hello", 42, 3.14, True, None)) == ["hello", 42, 3.14, True, None]

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


class TestLogToFile:
    """Tests for _log_to_file method (lines 133-139) — in-process, no hook needed."""

    def test_log_file_creates_parent_dirs(self, tmp_path: Path):
        """_log_to_file should create parent directories (line 134)."""
        nested_log = tmp_path / "deep" / "nested" / "audit.jsonl"
        hook = RuntimeAuditHook(log_file=nested_log)
        entry = {"event": "open", "args": [], "timestamp": "2026-01-01T00:00:00+00:00"}
        hook._log_to_file(entry)
        assert nested_log.exists()

    def test_log_file_writes_jsonl(self, tmp_path: Path):
        """_log_to_file should write a valid JSON line (line 135-136)."""
        log_file = tmp_path / "audit.jsonl"
        hook = RuntimeAuditHook(log_file=log_file)
        entry = {"event": "open", "args": ["/tmp/test"], "timestamp": "2026-01-01T00:00:00+00:00"}
        hook._log_to_file(entry)
        content = log_file.read_text(encoding="utf-8").strip()
        parsed = json.loads(content)
        assert parsed["event"] == "open"
        assert parsed["args"] == ["/tmp/test"]

    def test_log_file_appends(self, tmp_path: Path):
        """_log_to_file should append, not overwrite (line 135 'a' mode)."""
        log_file = tmp_path / "audit.jsonl"
        hook = RuntimeAuditHook(log_file=log_file)
        entry1 = {"event": "open", "args": [], "timestamp": "2026-01-01T00:00:00+00:00"}
        entry2 = {"event": "compile", "args": [], "timestamp": "2026-01-01T00:00:01+00:00"}
        hook._log_to_file(entry1)
        hook._log_to_file(entry2)
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "open"
        assert json.loads(lines[1])["event"] == "compile"

    def test_log_file_oserror_silently_ignored(self):
        """_log_to_file should silently ignore OSError (lines 137-139)."""
        # Use a path that will cause OSError
        hook = RuntimeAuditHook(log_file=Path("/proc/fake/impossible/audit.jsonl"))
        entry = {"event": "open", "args": [], "timestamp": "2026-01-01T00:00:00+00:00"}
        # Should not raise
        hook._log_to_file(entry)

    def test_log_file_permission_error_silently_ignored(self, tmp_path: Path):
        """_log_to_file should silently ignore PermissionError (OSError subclass)."""
        # Create a read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)
        log_file = readonly_dir / "audit.jsonl"
        hook = RuntimeAuditHook(log_file=log_file)
        entry = {"event": "open", "args": [], "timestamp": "2026-01-01T00:00:00+00:00"}
        try:
            # Should not raise
            hook._log_to_file(entry)
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)


class TestAuditHandlerInProcess:
    """Tests for the _audit_handler inner function — in-process via captured handler.

    sys.addaudithook callbacks are called from C level and are invisible to
    coverage.py. To achieve coverage, we capture the handler via a mock on
    sys.addaudithook, then call it directly from Python (where coverage can
    trace it).
    """

    @staticmethod
    def _install_and_capture_handler(**kwargs) -> tuple:
        """Install a hook with a mock on sys.addaudithook to capture the handler.

        Returns (hook_instance, handler_function).
        """
        captured_handler = None

        def capture_handler(handler_fn):
            nonlocal captured_handler
            captured_handler = handler_fn

        with patch.object(sys, "addaudithook", side_effect=capture_handler):
            hook = RuntimeAuditHook(**kwargs)
            hook.install(force=True)

        return hook, captured_handler

    def test_monitored_event_captured(self, tmp_path: Path):
        """Monitored events should be captured (lines 91-92, 101-107)."""
        hook, handler = self._install_and_capture_handler(log_file=tmp_path / "audit.jsonl")
        assert handler is not None

        # Call the handler directly — simulates sys.audit("open", path)
        handler("open", ("/tmp/test.txt", "r"))

        events = hook.get_events()
        open_events = [e for e in events if e["event"] == "open"]
        assert len(open_events) == 1

    def test_unmonitored_event_ignored(self, tmp_path: Path):
        """Non-monitored events should be silently ignored (lines 91-92)."""
        hook, handler = self._install_and_capture_handler(log_file=tmp_path / "audit.jsonl")

        # "import" is not in MONITORED_EVENTS
        handler("import", ("some_module",))

        events = hook.get_events()
        import_events = [e for e in events if e["event"] == "import"]
        assert len(import_events) == 0

    def test_event_entry_structure(self, tmp_path: Path):
        """Each captured event should have event, args, and timestamp (lines 101-105)."""
        hook, handler = self._install_and_capture_handler(log_file=tmp_path / "audit.jsonl")

        handler("open", ("/tmp/test.txt", "r"))

        events = hook.get_events()
        assert len(events) >= 1
        e = events[0]
        assert "event" in e
        assert "args" in e
        assert "timestamp" in e
        assert isinstance(e["args"], list)
        assert isinstance(e["event"], str)

    def test_callback_dispatched(self, tmp_path: Path):
        """When callback is set, it receives events (lines 109-110)."""
        callback_calls = []
        hook, handler = self._install_and_capture_handler(
            callback=lambda e, a: callback_calls.append((e, a)),
            log_file=tmp_path / "audit.jsonl",
        )

        handler("open", ("/tmp/test.txt", "r"))

        assert len(callback_calls) == 1
        assert callback_calls[0][0] == "open"
        # The callback receives the raw args tuple, not the serialized list
        assert callback_calls[0][1] == ("/tmp/test.txt", "r")

    def test_callback_skips_file_logging(self, tmp_path: Path):
        """When callback is set, _log_to_file should NOT be called (lines 109-112)."""
        log_file = tmp_path / "audit.jsonl"
        callback_calls = []
        hook, handler = self._install_and_capture_handler(
            callback=lambda e, a: callback_calls.append((e, a)),
            log_file=log_file,
        )

        handler("open", ("/tmp/test.txt", "r"))

        # With callback set, log file should NOT be written to
        assert not log_file.exists()

    def test_file_logging_when_no_callback(self, tmp_path: Path):
        """When no callback, events should be logged to file (lines 111-112)."""
        log_file = tmp_path / "audit.jsonl"
        hook, handler = self._install_and_capture_handler(log_file=log_file)

        handler("open", ("/tmp/test.txt", "r"))

        assert log_file.exists()
        lines = [line for line in log_file.read_text().strip().split("\n") if line]
        assert len(lines) >= 1
        parsed = json.loads(lines[0])
        assert "event" in parsed
        assert "timestamp" in parsed

    def test_reentrancy_guard(self, tmp_path: Path):
        """Reentrancy guard should prevent recursive events (lines 96-98, 113-114).

        When the handler is already processing (self._in_handler is True),
        subsequent events should be silently dropped.
        """
        hook, handler = self._install_and_capture_handler(log_file=tmp_path / "audit.jsonl")

        # Manually set _in_handler to simulate being mid-processing
        hook._in_handler = True
        handler("open", ("/tmp/test.txt", "r"))
        # Event should be dropped due to reentrancy guard
        assert len(hook.get_events()) == 0

        # Reset guard — now events should be captured again
        hook._in_handler = False
        handler("open", ("/tmp/test2.txt", "r"))
        assert len(hook.get_events()) == 1

    def test_finally_block_resets_guard(self, tmp_path: Path):
        """The reentrancy guard should be reset in finally block (lines 113-114).

        After handler completes, _in_handler should be False again.
        """
        hook, handler = self._install_and_capture_handler(log_file=tmp_path / "audit.jsonl")

        assert hook._in_handler is False
        handler("open", ("/tmp/test.txt", "r"))
        assert hook._in_handler is False  # Reset by finally block

    def test_compile_event_captured(self, tmp_path: Path):
        """compile events should be captured (line 91-92 filter passes)."""
        hook, handler = self._install_and_capture_handler(log_file=tmp_path / "audit.jsonl")

        handler("compile", ("1 + 1", "<test>", "eval"))

        events = hook.get_events()
        compile_events = [e for e in events if e["event"] == "compile"]
        assert len(compile_events) == 1

    def test_handler_with_none_log_file(self):
        """Handler should work with no log file (line 111-112 condition)."""
        hook, handler = self._install_and_capture_handler()

        # No callback, no log file — event should still be recorded
        handler("open", ("/tmp/test.txt", "r"))

        events = hook.get_events()
        assert len(events) == 1
        assert events[0]["event"] == "open"

    def test_multiple_events_captured_sequentially(self, tmp_path: Path):
        """Multiple events should all be captured (line 107 append)."""
        log_file = tmp_path / "audit.jsonl"
        hook, handler = self._install_and_capture_handler(log_file=log_file)

        handler("open", ("/tmp/a.txt", "r"))
        handler("open", ("/tmp/b.txt", "w"))
        handler("compile", ("code", "<test>", "exec"))

        events = hook.get_events()
        assert len(events) == 3


class TestInstallDoubleCheck:
    """Test for the redundant installed check on line 88."""

    def test_second_install_noop_in_prod(self):
        """Line 88: second self._installed check should prevent double registration.

        When SKILLPOOL_ENV=prod, the first install() registers the hook.
        A second install() should hit the _installed guard on line 88.
        """
        with patch.dict("os.environ", {"SKILLPOOL_ENV": "prod"}):
            with patch.object(sys, "addaudithook") as mock_add:
                hook = RuntimeAuditHook()
                hook.install()  # First install: registers the hook
                assert mock_add.call_count == 1
                hook.install()  # Second install: hits line 88 guard
                assert mock_add.call_count == 1  # Still only called once


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
            capture_output=True,
            text=True,
            timeout=30,
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
            capture_output=True,
            text=True,
            timeout=30,
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
            capture_output=True,
            text=True,
            timeout=30,
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
            capture_output=True,
            text=True,
            timeout=30,
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
            capture_output=True,
            text=True,
            timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        data = json.loads(result.stdout.strip())
        assert data["all_dicts"]
