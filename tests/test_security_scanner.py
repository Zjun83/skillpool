"""Tests for SecurityScanner — pre-materialization security checks.

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillpool.hooks.security_scanner import (
    SecurityCheckResult,
    SecurityScanner,
    ThreatLevel,
)


class TestThreatLevel:
    """Tests for ThreatLevel enum."""

    def test_values(self):
        assert ThreatLevel.SAFE.value == "safe"
        assert ThreatLevel.WARNING.value == "warning"
        assert ThreatLevel.CRITICAL.value == "critical"


class TestSecurityCheckResult:
    """Tests for SecurityCheckResult dataclass."""

    def test_safe_by_default(self):
        result = SecurityCheckResult(threat_level=ThreatLevel.SAFE)
        assert result.is_safe

    def test_warning_is_safe(self):
        result = SecurityCheckResult(threat_level=ThreatLevel.WARNING)
        assert result.is_safe

    def test_critical_is_not_safe(self):
        result = SecurityCheckResult(threat_level=ThreatLevel.CRITICAL)
        assert not result.is_safe


class TestYamlSafety:
    """Tests for YAML safety checks."""

    def test_safe_yaml(self):
        scanner = SecurityScanner()
        result = scanner.check_yaml_safety("name: test\nversion: 1.0\n")
        assert result.threat_level == ThreatLevel.SAFE
        assert "yaml_syntax" in result.checks_passed

    @pytest.mark.parametrize(
        "tag",
        [
            "!!python/object",
            "!!python/object/apply",
            "!!python/object/new",
            "!!python/module",
            "!!python/name",
        ],
    )
    def test_dangerous_yaml_tags(self, tag):
        scanner = SecurityScanner()
        content = f"value: {tag}:module.Class"
        result = scanner.check_yaml_safety(content)
        assert result.threat_level == ThreatLevel.CRITICAL
        assert any(tag in b for b in result.blockers)


class TestPatternScan:
    """Tests for dangerous pattern scanning."""

    def test_safe_content(self):
        scanner = SecurityScanner()
        content = "```python\nprint('hello')\nx = [1, 2, 3]\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.SAFE

    def test_exec_pattern_is_critical(self):
        # NOSONAR: testing detection of exec(), not using it
        scanner = SecurityScanner()
        content = "```python\nexec('print(1)')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.CRITICAL

    def test_eval_pattern_is_critical(self):
        # NOSONAR: testing detection of eval(), not using it
        scanner = SecurityScanner()
        content = "```python\neval('1+1')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.CRITICAL

    def test_os_system_is_critical(self):
        # NOSONAR: testing detection of os.system(), not using it
        scanner = SecurityScanner()
        content = "```python\nos.system('ls')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.CRITICAL

    def test_subprocess_is_warning(self):
        scanner = SecurityScanner()
        content = "```python\nsubprocess.run(['echo', 'hello'])\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)

    def test_commented_code_ignored(self):
        scanner = SecurityScanner()
        content = "```python\n# exec('dangerous')\nprint('safe')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.SAFE

    def test_no_code_blocks_safe(self):
        scanner = SecurityScanner()
        result = scanner.scan_dangerous_patterns("Just plain text, no code here.")
        assert result.threat_level == ThreatLevel.SAFE

    def test_custom_patterns(self):
        scanner = SecurityScanner(
            custom_patterns=[
                (r"\bdangerous_func\s*\(", "custom dangerous function"),
            ]
        )
        content = "```python\ndangerous_func()\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)


class TestSignatureVerification:
    """Tests for signature verification (placeholder)."""

    def test_dev_tier_passes_with_note(self):
        """Dev tier: signature check passes with informational note."""
        scanner = SecurityScanner()
        result = scanner.verify_signature(Path("/tmp/fake"))
        assert result.threat_level == ThreatLevel.SAFE
        assert "signature_check" in result.checks_passed
        assert any("dev tier" in w.lower() or "skipped" in w.lower() for w in result.warnings)

    def test_prod_tier_blocks_unsigned(self):
        """Prod tier: signature check returns CRITICAL (blocks materialization)."""
        scanner = SecurityScanner(evidence_tier="prod")
        result = scanner.verify_signature(Path("/tmp/fake"))
        assert result.threat_level == ThreatLevel.CRITICAL
        assert result.blockers
        assert "signature_check" in result.checks_passed

    def test_ci_tier_returns_warning(self):
        """CI tier: signature check returns WARNING."""
        scanner = SecurityScanner(evidence_tier="ci")
        result = scanner.verify_signature(Path("/tmp/fake"))
        assert result.threat_level == ThreatLevel.WARNING
        assert "signature_check" in result.checks_passed


class TestExtractCodeBlocks:
    """Tests for _extract_code_blocks — robust Markdown code block extraction."""

    def test_simple_backtick_fence(self):
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "```python\nprint('hello')\n```\n"
        result = _extract_code_blocks(content)
        assert "print('hello')" in result

    def test_tilde_fence(self):
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "~~~python\nprint('hello')\n~~~\n"
        result = _extract_code_blocks(content)
        assert "print('hello')" in result

    def test_unclosed_backtick_fence(self):
        """Unclosed fence → fallback: scan entire content minus the fence line."""
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "```python\nexec('dangerous')\n"
        result = _extract_code_blocks(content)
        # NOSONAR: testing detection, not execution
        assert "exec('dangerous')" in result

    def test_crlf_line_endings(self):
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "```python\r\nprint('hello')\r\n```\r\n"
        result = _extract_code_blocks(content)
        assert "print('hello')" in result

    def test_multiple_code_blocks(self):
        """Multiple code blocks — all blocks are extracted."""
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "```python\nprint('a')\n```\n```bash\necho b\n```\n"
        result = _extract_code_blocks(content)
        assert "print('a')" in result
        assert "echo b" in result

    def test_no_code_blocks_returns_full_content(self):
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "Just plain text, no code."
        result = _extract_code_blocks(content)
        assert result == content

    def test_inline_code(self):
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "Use `exec('x')` carefully."
        # NOSONAR: testing detection
        result = _extract_code_blocks(content)
        assert "exec('x')" in result

    def test_dangerous_pattern_in_second_block_detected(self):
        """exec() in a second code block must be detected (was a bug)."""
        scanner = SecurityScanner()
        # NOSONAR: testing detection
        content = "```python\nprint('safe')\n```\n```bash\nexec('malicious')\n```\n"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.CRITICAL

    def test_tilde_fence_with_backtick_inside(self):
        """Tilde fence containing backtick lines should not confuse the parser."""
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "~~~python\nprint('`hello`')\n~~~\n"
        result = _extract_code_blocks(content)
        assert "hello" in result

    def test_nested_fences(self):
        """Inner fence with different type should be treated as content."""
        from skillpool.hooks.security_scanner import _extract_code_blocks

        content = "~~~markdown\n```python\ncode\n```\n~~~\n"
        result = _extract_code_blocks(content)
        assert "code" in result


class TestSafeContextExclusion:
    """Verify _SAFE_CONTEXTS correctly excludes safe patterns from flagging."""

    def test_re_compile_not_flagged(self):
        """re.compile() is safe — should not be flagged as compile()."""
        scanner = SecurityScanner()
        content = "```python\npattern = re.compile(r'\\d+')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.SAFE

    def test_commented_exec_not_flagged(self):
        """Commented-out exec() should not be flagged."""
        scanner = SecurityScanner()
        # NOSONAR: testing detection of exec(), not using it
        content = "```python\n# exec('malicious')\nprint('safe')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.SAFE

    def test_docstring_line_with_triple_quotes_not_flagged(self):
        """A line containing both triple quotes and exec() is excluded."""
        scanner = SecurityScanner()
        # NOSONAR: testing detection
        content = '```python\n""" exec("example") """\n```'
        result = scanner.scan_dangerous_patterns(content)
        # Line contains """ so _SAFE_CONTEXTS matches
        assert result.threat_level == ThreatLevel.SAFE

    def test_docstring_interior_line_is_flagged(self):
        """Lines inside a docstring (without triple quotes) are still flagged.

        _SAFE_CONTEXTS is a simple line-level check — it cannot track
        multi-line docstring state. This is a known limitation.
        """
        scanner = SecurityScanner()
        # NOSONAR: testing detection
        content = '```python\n"""\nexec("example")\n"""\nprint("safe")\n```'
        result = scanner.scan_dangerous_patterns(content)
        # The exec line itself doesn't contain """, so it IS flagged
        assert result.threat_level == ThreatLevel.CRITICAL

    def test_triple_single_quote_line_not_flagged(self):
        """A line containing both triple single quotes and eval() is excluded."""
        scanner = SecurityScanner()
        # NOSONAR: testing detection
        content = "```python\n''' eval('example') '''\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.SAFE


class TestFullCheck:
    """Tests for full_check aggregation."""

    def test_safe_content_passes(self):
        scanner = SecurityScanner()
        result = scanner.full_check("name: test\nversion: 1.0\n")
        assert result.is_safe
        assert "yaml_syntax" in result.checks_passed
        assert "pattern_scan" in result.checks_passed

    def test_dangerous_content_blocked(self):
        # NOSONAR: testing detection, not execution
        scanner = SecurityScanner()
        content = "```python\nexec('malicious')\n```"
        result = scanner.full_check(content)
        assert not result.is_safe
        assert result.threat_level == ThreatLevel.CRITICAL

    def test_warning_content_allowed_but_flagged(self):
        scanner = SecurityScanner()
        content = "```python\nsubprocess.run(['ls'])\n```"
        result = scanner.full_check(content)
        assert result.is_safe or result.threat_level == ThreatLevel.CRITICAL
        # Should have at least a warning about subprocess
        assert len(result.warnings) > 0 or len(result.blockers) > 0

    def test_full_check_with_path_adds_signature(self):
        scanner = SecurityScanner()
        result = scanner.full_check("safe: true", Path("/tmp/test"))
        assert "signature_check" in result.checks_passed


class TestVerifySignatureEnvVar:
    """Tests for SKILLPOOL_EVIDENCE_TIER env var override."""

    def test_env_var_prod_overrides_default(self, monkeypatch):
        """SKILLPOOL_EVIDENCE_TIER=prod should override default dev behavior."""
        monkeypatch.setenv("SKILLPOOL_EVIDENCE_TIER", "prod")
        scanner = SecurityScanner()  # No evidence_tier arg, defaults to None
        result = scanner.verify_signature(Path("/tmp/fake"))
        # Env var = prod → CRITICAL (blocks materialization)
        assert result.threat_level == ThreatLevel.CRITICAL
        assert result.blockers

    def test_env_var_ci_overrides_default(self, monkeypatch):
        """SKILLPOOL_EVIDENCE_TIER=ci should override default dev behavior."""
        monkeypatch.setenv("SKILLPOOL_EVIDENCE_TIER", "ci")
        scanner = SecurityScanner()
        result = scanner.verify_signature(Path("/tmp/fake"))
        assert result.threat_level == ThreatLevel.WARNING

    def test_env_var_dev_explicit(self, monkeypatch):
        """SKILLPOOL_EVIDENCE_TIER=dev should allow signature skip."""
        monkeypatch.setenv("SKILLPOOL_EVIDENCE_TIER", "dev")
        scanner = SecurityScanner()
        result = scanner.verify_signature(Path("/tmp/fake"))
        assert result.threat_level == ThreatLevel.SAFE
        assert any("dev" in w.lower() or "skipped" in w.lower() for w in result.warnings)

    def test_explicit_tier_overrides_env_var(self, monkeypatch):
        """Explicit evidence_tier arg should take precedence over env var."""
        monkeypatch.setenv("SKILLPOOL_EVIDENCE_TIER", "prod")
        scanner = SecurityScanner(evidence_tier="dev")
        result = scanner.verify_signature(Path("/tmp/fake"))
        # Explicit tier=dev overrides env=prod → SAFE
        assert result.threat_level == ThreatLevel.SAFE


class TestYamlSafetyAdditionalTags:
    """Additional YAML safety edge cases."""

    def test_python_object_subclass_detected(self):
        """!!python/object/subclass should be flagged."""
        scanner = SecurityScanner()
        content = "!!python/object/subclass:os._Environ\n{}"
        result = scanner.check_yaml_safety(content)
        assert result.threat_level == ThreatLevel.CRITICAL
        assert any("subclass" in b for b in result.blockers)

    def test_multiple_dangerous_tags_in_one_content(self):
        """Content with multiple dangerous tags should flag all."""
        scanner = SecurityScanner()
        content = "a: !!python/object:foo.Bar\nb: !!python/name:os.system"
        result = scanner.check_yaml_safety(content)
        assert result.threat_level == ThreatLevel.CRITICAL
        assert len(result.blockers) >= 2

    def test_safe_yaml_with_equals_sign(self):
        """YAML with regular content containing '!!' but not dangerous tags."""
        scanner = SecurityScanner()
        # Regular YAML — no dangerous tags even though it has !!python syntax-like text
        content = "description: This skill does not use !!python tags"
        result = scanner.check_yaml_safety(content)
        # "!!python" substring appears, but not as a YAML tag prefix
        # The check only looks for exact tag prefixes like "!!python/object"
        assert result.threat_level == ThreatLevel.SAFE


class TestDangerousPatternsComprehensive:
    """Comprehensive tests for all dangerous pattern detections."""

    def test_os_popen_detected(self):
        """os.popen() should be flagged as WARNING."""
        scanner = SecurityScanner()
        content = "```python\nos.popen('whoami')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)
        assert any(
            "os.popen" in w or "os.popen" in b
            for w, b in [(w, "") for w in result.warnings] + [(b, b) for b in result.blockers]
        )

    def test_import_detected(self):
        """__import__() should be flagged."""
        scanner = SecurityScanner()
        content = "```python\n__import__('os')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)
        assert any("__import__" in w for w in result.warnings) or any("__import__" in b for b in result.blockers)

    def test_shutil_rmtree_detected(self):
        """shutil.rmtree() should be flagged."""
        scanner = SecurityScanner()
        content = "```python\nshutil.rmtree('/tmp/x')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)

    def test_os_remove_detected(self):
        """os.remove() should be flagged."""
        scanner = SecurityScanner()
        content = "```python\nos.remove('/tmp/secret')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)

    def test_os_unlink_detected(self):
        """os.unlink() should be flagged."""
        scanner = SecurityScanner()
        content = "```python\nos.unlink('/tmp/secret')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)

    def test_compile_detected(self):
        """compile() should be flagged (not re.compile)."""
        scanner = SecurityScanner()
        content = "```python\ncompile('code', 'file', 'exec')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)
        assert any("compile" in w for w in result.warnings) or any("compile" in b for b in result.blockers)

    def test_file_write_detected(self):
        """open() with write mode should be flagged."""
        scanner = SecurityScanner()
        content = "```python\nwith open('out.txt', 'w') as f:\n    f.write('data')\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)

    def test_safe_open_read_not_flagged(self):
        """open() in read mode should NOT be flagged."""
        scanner = SecurityScanner()
        content = "```python\nwith open('in.txt', 'r') as f:\n    data = f.read()\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level == ThreatLevel.SAFE


class TestFullCheckAggregation:
    """Additional tests for full_check aggregation logic."""

    def test_full_check_without_skill_path_no_signature(self):
        """full_check without skill_path should not include signature check."""
        scanner = SecurityScanner()
        result = scanner.full_check("name: test\nversion: 1.0\n")
        assert "yaml_syntax" in result.checks_passed
        assert "pattern_scan" in result.checks_passed
        assert "signature_check" not in result.checks_passed

    def test_full_check_critical_yaml_overrides_safe_patterns(self):
        """YAML critical finding should dominate over safe patterns."""
        scanner = SecurityScanner()
        content = "!!python/object:evil.Class\n```python\nprint('hello')\n```"
        result = scanner.full_check(content)
        assert result.threat_level == ThreatLevel.CRITICAL
        assert not result.is_safe

    def test_full_check_dev_tier_safe_overall(self):
        """Dev tier content that is safe in both checks should be overall safe."""
        scanner = SecurityScanner()
        content = "name: test\n```python\nx = 1\n```"
        result = scanner.full_check(content, Path("/tmp/test"))
        assert result.is_safe
        assert len(result.checks_passed) == 3

    def test_full_check_prod_tier_blocks_even_safe_content(self):
        """Prod tier should block on signature even if content is safe."""
        scanner = SecurityScanner(evidence_tier="prod")
        content = "name: safe-skill\nversion: 1.0"
        result = scanner.full_check(content, Path("/tmp/test"))
        assert result.threat_level == ThreatLevel.CRITICAL
        assert not result.is_safe
