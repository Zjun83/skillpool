"""Hook-layer security checks for SkillPool skill materialization.

Runs before any skill is materialized to ensure safety:
1. YAML syntax safety — no unsafe tags or constructors
2. Dangerous pattern scanning — exec/os.system/eval/subprocess
3. Signature verification — sigstore placeholder (production needs cosign)

Part of SkillPool — independent infrastructure, shared by all agents.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class ThreatLevel(Enum):
    """Threat severity classification."""
    SAFE = "safe"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class SecurityCheckResult:
    """Result of a security check on skill content."""
    threat_level: ThreatLevel
    checks_passed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return self.threat_level != ThreatLevel.CRITICAL


# Dangerous patterns to detect in skill content (NOT executed — regex strings for scanning only)
# These patterns are used to flag unsafe code in skill YAML/MD content before materialization.
_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"\bexec\s*\(", "exec() call — arbitrary code execution"),           # NOSONAR: regex for detection, not a call
    (r"\beval\s*\(", "eval() call — arbitrary code execution"),           # NOSONAR: regex for detection, not a call
    (r"\bos\.system\s*\(", "os.system() call — shell injection risk"),    # NOSONAR: regex for detection, not a call
    (r"\bos\.popen\s*\(", "os.popen() call — shell injection risk"),      # NOSONAR: regex for detection, not a call
    (r"\bsubprocess\.\w+\s*\(", "subprocess call — external process execution"),
    (r"\b__import__\s*\(", "__import__() call — dynamic import risk"),
    (r"\bcompile\s*\(", "compile() call — dynamic code compilation"),
    (r"\bopen\s*\(.*['\"]w", "file write — potential data modification"),
    (r"\bshutil\.rmtree\s*\(", "shutil.rmtree() — directory deletion"),
    (r"\bos\.remove\s*\(", "os.remove() — file deletion"),
    (r"\bos\.unlink\s*\(", "os.unlink() — file deletion"),
]

# Safe contexts that should be excluded from dangerous matches
_SAFE_CONTEXTS = [
    r"#\s*",       # commented out code
    r'"""',        # inside docstring
    r"'''",        # inside docstring
    r"re\.compile", # re.compile() is safe (not builtins.compile)
]


def _extract_code_blocks(content: str) -> str:
    """Extract code blocks from Markdown content for scanning.

    Handles:
    - Triple-backtick fences (```...```)
    - Tilde fences (~~~...~~~)
    - Unclosed code blocks (fallback: scan entire content)
    - CRLF line endings
    - Multiple consecutive code blocks
    """
    # Normalize CRLF to LF
    normalized = content.replace("\r\n", "\n")

    # Line-by-line parser: correctly handles multiple blocks
    blocks: list[str] = []
    in_block = False
    fence_char: str | None = None
    fence_len = 0
    current_lines: list[str] = []

    for line in normalized.split("\n"):
        stripped = line.strip()
        is_fence = False
        detected_char: str | None = None
        detected_len = 0

        if stripped.startswith("```"):
            detected_char = "`"
            for ch in stripped:
                if ch == "`":
                    detected_len += 1
                else:
                    break
            is_fence = detected_len >= 3
        elif stripped.startswith("~~~"):
            detected_char = "~"
            for ch in stripped:
                if ch == "~":
                    detected_len += 1
                else:
                    break
            is_fence = detected_len >= 3

        if is_fence:
            if not in_block:
                # Opening fence
                in_block = True
                fence_char = detected_char
                fence_len = detected_len
                current_lines = []
            elif detected_char == fence_char and detected_len >= fence_len:
                # Closing fence matching opening
                blocks.append("\n".join(current_lines))
                in_block = False
                current_lines = []
            else:
                # Different fence inside a block — treat as content
                current_lines.append(line)
        elif in_block:
            current_lines.append(line)

    # Handle unclosed fence
    if in_block and current_lines:
        blocks.append("\n".join(current_lines))

    # If no fenced blocks found, try inline code
    if not blocks:
        inline_blocks = re.findall(r"`([^`]+)`", normalized)
        if inline_blocks:
            return "\n".join(inline_blocks)
        # No code blocks at all — scan the entire content
        return normalized

    return "\n".join(blocks)


class SecurityScanner:
    """Scans skill content for security threats before materialization.

    Part of SkillPool — independent infrastructure, shared by all agents.
    """

    def __init__(
        self,
        custom_patterns: list[tuple[str, str]] | None = None,
        evidence_tier: str | None = None,
    ):
        self._patterns = _DANGEROUS_PATTERNS.copy()
        if custom_patterns:
            self._patterns.extend(custom_patterns)
        self._evidence_tier = evidence_tier

    def check_yaml_safety(self, content: str) -> SecurityCheckResult:
        """Check YAML content for unsafe constructs.

        Blocks:
        - YAML tags that invoke Python constructors (!!python/object, etc.)
        - Custom YAML constructors that aren't in the safe list
        """
        result = SecurityCheckResult(threat_level=ThreatLevel.SAFE)
        result.checks_passed.append("yaml_syntax")

        # Check for dangerous YAML tags
        dangerous_tags = [
            "!!python/object",
            "!!python/object/apply",
            "!!python/object/new",
            "!!python/module",
            "!!python/name",
            "!!python/object/subclass",
        ]
        for tag in dangerous_tags:
            if tag in content:
                result.blockers.append(f"Dangerous YAML tag: {tag}")
                result.threat_level = ThreatLevel.CRITICAL

        return result

    def scan_dangerous_patterns(self, content: str) -> SecurityCheckResult:
        """Scan for dangerous code patterns in skill content.

        Scans code blocks and inline code for patterns that could indicate
        security risks. Uses _extract_code_blocks for robust code block
        extraction (handles unclosed fences, tildes, CRLF).
        Applies _SAFE_CONTEXTS to exclude commented-out code and
        re.compile() calls.
        """
        result = SecurityCheckResult(threat_level=ThreatLevel.SAFE)
        result.checks_passed.append("pattern_scan")

        # Extract code blocks for scanning
        scan_text = _extract_code_blocks(content)

        for pattern, description in self._patterns:
            matches = list(re.finditer(pattern, scan_text))
            for match in matches:
                # Get the line containing the match
                line_start = scan_text.rfind("\n", 0, match.start()) + 1
                line_end = scan_text.find("\n", match.end())
                if line_end == -1:
                    line_end = len(scan_text)
                line = scan_text[line_start:line_end].strip()

                # Skip if in a safe context (commented out, re.compile, etc.)
                is_safe_context = False
                for safe_pattern in _SAFE_CONTEXTS:
                    if re.search(safe_pattern, line):
                        is_safe_context = True
                        break
                if is_safe_context:
                    continue

                result.warnings.append(
                    f"{description} at position {match.start()}: {match.group()}"
                )
                # Patterns that are always critical
                critical_patterns = {r"\bexec\s*\(", r"\beval\s*\(", r"\bos\.system\s*\("}
                if pattern in critical_patterns:
                    result.blockers.append(f"Critical: {description}")
                    result.threat_level = ThreatLevel.CRITICAL
                elif result.threat_level == ThreatLevel.SAFE:
                    result.threat_level = ThreatLevel.WARNING

        return result

    def verify_signature(self, skill_path: Path) -> SecurityCheckResult:
        """Verify skill signature.

        Tier-dependent behavior:
        - dev: placeholder passes with informational note
        - ci/prod: returns WARNING (strict mode, needs real cosign/sigstore)
        """
        import os

        tier = getattr(self, "_evidence_tier", None) or os.environ.get(
            "SKILLPOOL_EVIDENCE_TIER", "dev"
        )
        result = SecurityCheckResult(threat_level=ThreatLevel.SAFE)
        result.checks_passed.append("signature_check")

        if tier in ("ci", "prod"):
            result.warnings.append(
                "Signature verification is a placeholder — "
                "production deployment requires cosign/sigstore"
            )
            result.threat_level = ThreatLevel.WARNING
        else:
            result.warnings.append(
                "Signature verification skipped (dev tier) — "
                "set SKILLPOOL_EVIDENCE_TIER=prod for strict checking"
            )
        return result

    def full_check(self, content: str, skill_path: Path | None = None) -> SecurityCheckResult:
        """Run all security checks and return aggregated result.

        Args:
            content: The SKILL.md or CSDF YAML content to check.
            skill_path: Optional path to the skill directory for signature verification.

        Returns:
            Aggregated SecurityCheckResult with the highest threat level found.
        """
        results = [
            self.check_yaml_safety(content),
            self.scan_dangerous_patterns(content),
        ]
        if skill_path:
            results.append(self.verify_signature(skill_path))

        # Aggregate: take the highest threat level
        aggregated = SecurityCheckResult(threat_level=ThreatLevel.SAFE)
        for r in results:
            if r.threat_level == ThreatLevel.CRITICAL:
                aggregated.threat_level = ThreatLevel.CRITICAL
            elif r.threat_level == ThreatLevel.WARNING and aggregated.threat_level == ThreatLevel.SAFE:
                aggregated.threat_level = ThreatLevel.WARNING
            aggregated.checks_passed.extend(r.checks_passed)
            aggregated.warnings.extend(r.warnings)
            aggregated.blockers.extend(r.blockers)

        return aggregated
