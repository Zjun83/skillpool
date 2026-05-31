#!/usr/bin/env python3
"""gen_code_map_py.py — Zero-dependency Python fallback for symbol extraction.

Uses ast module for Python (precise), regex for Go/Rust/JS/TS (best-effort).
Generates symbol-index.json compatible with scaffold-docs CODE_MAP.md.

Usage:
    python3 gen_code_map_py.py --source src/ --output docs/symbol-index.json
    python3 gen_code_map_py.py --source src/ --output docs/symbol-index.json --verbose
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

VERSION = "1.0.0"

# ─── Python: ast-based precise extraction ───

def extract_python(filepath: Path, verbose: bool = False) -> list[dict[str, Any]]:
    """Extract classes, functions, and async functions from Python source using ast."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, ValueError) as e:
        if verbose:
            print(f"  [warn] Cannot parse {filepath}: {e}", file=sys.stderr)
        return []

    results: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Collect base classes for richer metadata
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(ast.dump(base))

            results.append({
                "type": "class",
                "name": node.name,
                "file": str(filepath),
                "line": node.lineno,
                "bases": bases,
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            # Detect if it's a method (inside a class)
            results.append({
                "type": kind,
                "name": node.name,
                "file": str(filepath),
                "line": node.lineno,
                "decorators": [
                    d.id if isinstance(d, ast.Name) else (d.attr if isinstance(d, ast.Attribute) else "")
                    for d in node.decorator_list
                    if isinstance(d, (ast.Name, ast.Attribute))
                ],
            })
    return results


# ─── Go/Rust/JS/TS: regex-based best-effort extraction ───

REGEX_PATTERNS: dict[str, tuple[str, int]] = {
    # Go: func (receiver) Name(...) or func Name(...)
    ".go": (r'^\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)', 1),
    # Rust: pub fn name, fn name, struct Name, enum Name, trait Name, impl Name
    ".rs": (r'^\s*(?:pub\s+)?(?:fn|struct|enum|trait|impl)\s+(\w+)', 1),
    # JavaScript: export function name, function name, export class name, class name, const name = ...
    ".js": (r'^\s*(?:export\s+)?(?:function|class)\s+(\w+)', 1),
    # TypeScript: same as JS + interface + type
    ".ts": (r'^\s*(?:export\s+)?(?:function|class|interface|type)\s+(\w+)', 1),
    # TypeScript JSX
    ".tsx": (r'^\s*(?:export\s+)?(?:function|class|interface|type)\s+(\w+)', 1),
    # JSX
    ".jsx": (r'^\s*(?:export\s+)?(?:function|class)\s+(\w+)', 1),
}

# Map file extensions to symbol type labels for the regex path
EXT_TYPE_MAP: dict[str, str] = {
    ".go": "func",
    ".rs": "symbol",
    ".js": "symbol",
    ".ts": "symbol",
    ".tsx": "symbol",
    ".jsx": "symbol",
}

# Directories to skip during traversal
SKIP_DIRS: set[str] = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    "dist", "build", ".eggs", ".scaffold-docs",
}


def extract_regex(filepath: Path, verbose: bool = False) -> list[dict[str, Any]]:
    """Extract symbols from non-Python source files using regex patterns."""
    ext = filepath.suffix
    if ext not in REGEX_PATTERNS:
        return []

    pattern, group_idx = REGEX_PATTERNS[ext]
    compiled = re.compile(pattern)
    results: list[dict[str, Any]] = []

    try:
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        if verbose:
            print(f"  [warn] Cannot read {filepath}: {e}", file=sys.stderr)
        return []

    for i, line in enumerate(lines, 1):
        m = compiled.match(line)
        if m:
            name = m.group(group_idx)
            # Filter out common false positives
            if name in ("_", "main", "init", "String", "Error"):
                continue
            results.append({
                "type": EXT_TYPE_MAP.get(ext, "symbol"),
                "name": name,
                "file": str(filepath),
                "line": i,
            })
    return results


# ─── Directory traversal ───

def should_skip_dir(d: Path) -> bool:
    """Check if a directory should be skipped during traversal."""
    return d.name in SKIP_DIRS or d.name.startswith(".")


def extract_all(source_dir: str, verbose: bool = False) -> list[dict[str, Any]]:
    """Walk source_dir and extract symbols from all supported files."""
    source_path = Path(source_dir)
    if not source_path.is_dir():
        print(f"[error] Source directory not found: {source_dir}", file=sys.stderr)
        return []

    results: list[dict[str, Any]] = []
    py_count = 0
    other_count = 0

    for filepath in sorted(source_path.rglob("*")):
        # Skip hidden and excluded directories
        if any(should_skip_dir(p) for p in filepath.relative_to(source_path).parents):
            continue
        if not filepath.is_file():
            continue

        ext = filepath.suffix
        if ext == ".py":
            symbols = extract_python(filepath, verbose)
            results.extend(symbols)
            py_count += 1
        elif ext in REGEX_PATTERNS:
            symbols = extract_regex(filepath, verbose)
            results.extend(symbols)
            other_count += 1

    if verbose:
        print(f"  Scanned {py_count} Python files, {other_count} other files", file=sys.stderr)

    return results


# ─── Output formatting ───

def format_json(symbols: list[dict[str, Any]], indent: int = 2) -> str:
    """Format symbols as JSON with metadata header."""
    output = {
        "_meta": {
            "generator": f"gen_code_map_py.py v{VERSION}",
            "symbol_count": len(symbols),
        },
        "symbols": symbols,
    }
    return json.dumps(output, indent=indent, ensure_ascii=False)


def format_markdown_table(symbols: list[dict[str, Any]]) -> str:
    """Format symbols as a Markdown table for CODE_MAP.md integration."""
    if not symbols:
        return "| Type | Name | File | Line |\n|------|------|------|------|\n| — | — | — | — |\n"

    lines = ["| Type | Name | File | Line |", "|------|------|------|------|"]
    for s in symbols:
        # Make file path relative-looking
        fpath = s["file"]
        lines.append(f"| {s['type']} | `{s['name']}` | `{fpath}` | {s['line']} |")
    return "\n".join(lines)


# ─── CLI ───

def main() -> None:
    import argparse

    p = argparse.ArgumentParser(
        description="Generate symbol-index.json (Python fallback, zero external dependencies)"
    )
    p.add_argument("--source", default="src/", help="Source directory to scan (default: src/)")
    p.add_argument("--output", default="docs/symbol-index.json",
                   help="Output JSON file path (default: docs/symbol-index.json)")
    p.add_argument("--format", choices=["json", "markdown"], default="json",
                   help="Output format (default: json)")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    p.add_argument("--version", action="version", version=f"%(prog)s v{VERSION}")
    args = p.parse_args()

    symbols = extract_all(args.source, verbose=args.verbose)

    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "json":
        content = format_json(symbols)
        output_path.write_text(content, encoding="utf-8")
        print(f"[scaffold-docs] {len(symbols)} symbols -> {args.output}")
    elif args.format == "markdown":
        content = format_markdown_table(symbols)
        output_path.write_text(content, encoding="utf-8")
        print(f"[scaffold-docs] {len(symbols)} symbols -> {args.output} (markdown table)")

    # Update CODE_MAP.md version if it exists
    code_map = Path("CODE_MAP.md")
    if code_map.exists():
        _bump_code_map_version(code_map)


def _bump_code_map_version(code_map: Path) -> None:
    """Increment the PATCH version in CODE_MAP.md frontmatter and update last_verified."""
    import re
    from datetime import datetime, timezone

    content = code_map.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()

    # Increment version: "1.0" -> "1.1", "1.5" -> "1.6"
    def bump_version(match: re.Match) -> str:
        major, minor = match.group(1), match.group(2)
        return f'version: "{major}.{int(minor) + 1}"'

    content = re.sub(r'^version: "(\d+)\.(\d+)"', bump_version, content, flags=re.MULTILINE)
    content = re.sub(r'^last_verified: .*', f'last_verified: "{now}"', content, flags=re.MULTILINE)
    code_map.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
