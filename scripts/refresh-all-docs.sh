#!/usr/bin/env bash
# refresh-all-docs.sh — Regenerate all auto-refreshable documentation
#
# Runs gen-code-map.sh and validate-links.sh in sequence.
# Updates symbol-index.json, CODE_MAP.md version, and reports broken links.
#
# Usage:
#   scripts/refresh-all-docs.sh [SOURCE_DIR] [OUTPUT_DIR]
#   scripts/refresh-all-docs.sh src/ docs/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="${1:-src/}"
OUTPUT_DIR="${2:-docs/}"
DRY_RUN="${REFRESH_DRY_RUN:-false}"

echo "=== refresh-all-docs: Starting full documentation refresh ==="
echo ""

# ─── Step 1: Regenerate symbol index ───

echo "[1/3] Running gen-code-map.sh ..."
if [ "$DRY_RUN" = "true" ]; then
    echo "  (dry run, skipping)"
else
    "${SCRIPT_DIR}/gen-code-map.sh" "$SOURCE_DIR" "$OUTPUT_DIR"
fi
echo ""

# ─── Step 2: Validate internal links ───

echo "[2/3] Running validate-links.sh ..."
if [ "$DRY_RUN" = "true" ]; then
    echo "  (dry run, skipping)"
else
    "${SCRIPT_DIR}/validate-links.sh" . || true
fi
echo ""

# ─── Step 3: Check document staleness ───

echo "[3/3] Running check-doc-staleness.sh ..."
if [ "$DRY_RUN" = "true" ]; then
    echo "  (dry run, skipping)"
else
    "${SCRIPT_DIR}/check-doc-staleness.sh" . || true
fi
echo ""

# ─── Summary ───

echo "=== refresh-all-docs: Complete ==="
echo "  Symbol index: ${OUTPUT_DIR}symbol-index.json"
echo "  CODE_MAP.md version: bumped (if file exists)"
echo ""
echo "Next steps:"
echo "  1. Review CODE_MAP.md module index table for accuracy"
echo "  2. Fix any broken links reported by validate-links.sh"
echo "  3. Update any stale documents flagged by check-doc-staleness.sh"
