#!/usr/bin/env bash
# gen-code-map.sh — Generate symbol-index.json using rg+jq (fast) or Python fallback
#
# Extracts class/function/method definitions from source code and produces
# a machine-readable JSON index. When ripgrep (rg) or jq are unavailable,
# automatically falls back to gen_code_map_py.py (Python ast + regex).
#
# Usage:
#   scripts/gen-code-map.sh [SOURCE_DIR] [OUTPUT_DIR]
#   scripts/gen-code-map.sh src/ docs/
#   scripts/gen-code-map.sh           # defaults: src/ docs/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="${1:-src/}"
OUTPUT_DIR="${2:-docs/}"
OUTPUT_JSON="${OUTPUT_DIR}symbol-index.json"

mkdir -p "$OUTPUT_DIR"

# ─── Fast path: rg + jq ───

if command -v rg >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
    echo "[gen-code-map] Using rg+jq (fast path)"

    rg --json \
       --type-add 'python:*.py' \
       --type-add 'go:*.go' \
       --type-add 'rust:*.rs' \
       --type-add 'js:*.js' \
       --type-add 'ts:*.ts' \
       -t python -t go -t rust -t js -t ts \
       '^\s*(class |def |async def |func |type |pub fn |pub struct |pub enum |impl |export function |export class |export interface |export type |function |const )' \
       "$SOURCE_DIR" 2>/dev/null | \
    jq -s '
        [ .[] | select(.type == "match") | {
            type: (
                if .data.lines.text | test("^\\s*class ") then "class"
                elif .data.lines.text | test("^\\s*async def ") then "async_function"
                elif .data.lines.text | test("^\\s*def ") then "function"
                elif .data.lines.text | test("^\\s*func ") then "func"
                elif .data.lines.text | test("^\\s*(pub )?struct ") then "struct"
                elif .data.lines.text | test("^\\s*(pub )?enum ") then "enum"
                elif .data.lines.text | test("^\\s*(pub )?trait ") then "trait"
                elif .data.lines.text | test("^\\s*impl ") then "impl"
                elif .data.lines.text | test("^\\s*export (function|class|interface|type) ") then "export"
                else "symbol"
                end
            ),
            name: (
                .data.lines.text
                | split("(")[0]
                | split(":")[0]
                | split(" ")[-1]
                | gsub("[^a-zA-Z0-9_]"; "")
            ),
            file: .data.path.text,
            line: .data.line_number
        } | select(.name != "" and .name != "_") ]
    ' > "$OUTPUT_JSON" 2>/dev/null

    # If rg found nothing (empty or error), still produce valid JSON
    if [ ! -s "$OUTPUT_JSON" ]; then
        echo '{"_meta": {"generator": "gen-code-map.sh (rg+jq)", "symbol_count": 0}, "symbols": []}' > "$OUTPUT_JSON"
    fi

    echo "[gen-code-map] Done: $(python3 -c "import json; d=json.load(open('$OUTPUT_JSON')); print(d.get('_meta',{}).get('symbol_count', len(d) if isinstance(d, list) else 0))" 2>/dev/null || echo '?') symbols -> $OUTPUT_JSON"

# ─── Fallback path: Python ast + regex ───

else
    echo "[gen-code-map] rg/jq not found, using Python fallback"
    python3 "${SCRIPT_DIR}/gen_code_map_py.py" --source "$SOURCE_DIR" --output "$OUTPUT_JSON" ${VERBOSE:+--verbose}
fi

# ─── Update CODE_MAP.md version ───

CODE_MAP="CODE_MAP.md"
if [ -f "$CODE_MAP" ]; then
    # Increment PATCH version in frontmatter
    python3 -c "
import re
from datetime import datetime, timezone
p = '$CODE_MAP'
with open(p, 'r') as f:
    content = f.read()
def bump(m):
    major, minor = m.group(1), m.group(2)
    return f'version: \"{major}.{int(minor)+1}\"'
content = re.sub(r'^version: \"(\d+)\.(\d+)\"', bump, content, flags=re.MULTILINE)
now = datetime.now(timezone.utc).isoformat()
content = re.sub(r'^last_verified: .*', f'last_verified: \"{now}\"', content, flags=re.MULTILINE)
with open(p, 'w') as f:
    f.write(content)
" 2>/dev/null || true
    echo "[gen-code-map] CODE_MAP.md version bumped"
fi

echo "[gen-code-map] Complete"
