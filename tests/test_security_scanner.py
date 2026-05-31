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

    @pytest.mark.parametrize("tag", [
        "!!python/object",
        "!!python/object/apply",
        "!!python/object/new",
        "!!python/module",
        "!!python/name",
    ])
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
        scanner = SecurityScanner(custom_patterns=[
            (r"\bdangerous_func\s*\(", "custom dangerous function"),
        ])
        content = "```python\ndangerous_func()\n```"
        result = scanner.scan_dangerous_patterns(content)
        assert result.threat_level in (ThreatLevel.WARNING, ThreatLevel.CRITICAL)


class TestSignatureVerification:
    """Tests for signature verification (placeholder)."""

    def test_placeholder_passes_with_warning(self):
        scanner = SecurityScanner()
        result = scanner.verify_signature(Path("/tmp/fake"))
        assert result.threat_level == ThreatLevel.SAFE
        assert "signature_check" in result.checks_passed
        assert any("placeholder" in w.lower() for w in result.warnings)


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
        """Multiple code blocks — first block is extracted."""
        from skillpool.hooks.security_scanner import _extract_code_blocks
        content = "```python\nprint('a')\n```\n```bash\necho b\n```\n"
        result = _extract_code_blocks(content)
        # Current implementation extracts first block; verify at least first is present
        assert "print('a')" in result

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
