#!/usr/bin/env bash
# health-check.sh — scaffold-docs environment health check
# Checks required and optional tool dependencies, reports pass/warn/fail.
# Exit 1 if any required dependency is missing.
#
# Usage: scripts/health-check.sh [--json]
#   --json  Output structured JSON report instead of human-readable

set -euo pipefail

SCRIPT_VERSION="1.0.0"
PASS=0
FAIL=0
WARN=0
RESULTS=()
JSON_MODE=false

if [ "${1:-}" = "--json" ]; then
    JSON_MODE=true
fi

check() {
    local name="$1" cmd="$2" required="${3:-true}" min_ver="${4:-}"
    local status="" ver="" detail=""

    if command -v "$cmd" >/dev/null 2>&1; then
        ver=$("$cmd" --version 2>/dev/null | head -1 || echo "ok")
        # Validate minimum version if specified
        if [ -n "$min_ver" ] && [ "$ver" != "ok" ]; then
            local ver_num
            ver_num=$(echo "$ver" | grep -oE '[0-9]+\.[0-9]+' | head -1 || echo "0.0")
            local min_num
            min_num=$(echo "$min_ver" | grep -oE '[0-9]+\.[0-9]+' | head -1)
            if [ "$(printf '%s\n' "$min_num" "$ver_num" | sort -V | head -1)" != "$min_num" ]; then
                status="fail"
                detail="${name}: ${ver} (requires >=${min_ver})"
                FAIL=$((FAIL+1))
            else
                status="pass"
                detail="${name}: ${ver}"
                PASS=$((PASS+1))
            fi
        else
            status="pass"
            detail="${name}: ${ver}"
            PASS=$((PASS+1))
        fi
    else
        if [ "$required" = "true" ]; then
            status="fail"
            detail="${name}: NOT FOUND (required)"
            FAIL=$((FAIL+1))
        else
            status="warn"
            detail="${name}: NOT FOUND (optional, fallback available)"
            WARN=$((WARN+1))
        fi
    fi

    RESULTS+=("${status}|${cmd}|${detail}|${required}")
}

# ─── Run checks ───

check "Python3" python3 true "3.10"
check "ripgrep" rg false "13.0"
check "jq" jq false "1.6"
check "git" git false "2.30"

# ─── Output ───

if [ "$JSON_MODE" = true ]; then
    # Structured JSON output
    python3 -c "
import json, sys
results = []
for r in '''$(printf '%s\n' "${RESULTS[@]}")'''.strip().split('\n'):
    parts = r.split('|')
    if len(parts) == 4:
        status, cmd, detail, required = parts
        results.append({'tool': cmd, 'status': status, 'detail': detail, 'required': required == 'true'})
print(json.dumps({
    'skill': 'scaffold-docs',
    'version': '${SCRIPT_VERSION}',
    'passed': ${FAIL} == 0,
    'summary': {'pass': ${PASS}, 'warn': ${WARN}, 'fail': ${FAIL}},
    'checks': results
}, indent=2))
"
else
    echo "=== scaffold-docs Health Check v${SCRIPT_VERSION} ==="
    echo ""
    echo "[Required]"
    for r in "${RESULTS[@]}"; do
        IFS='|' read -r status cmd detail required <<< "$r"
        if [ "$required" = "true" ]; then
            if [ "$status" = "pass" ]; then
                echo "  [PASS] ${detail}"
            else
                echo "  [FAIL] ${detail}"
            fi
        fi
    done
    echo ""
    echo "[Optional (with fallback)]"
    for r in "${RESULTS[@]}"; do
        IFS='|' read -r status cmd detail required <<< "$r"
        if [ "$required" = "false" ]; then
            if [ "$status" = "pass" ]; then
                echo "  [PASS] ${detail}"
            elif [ "$status" = "warn" ]; then
                echo "  [WARN] ${detail}"
                case "$cmd" in
                    rg)  echo "         -> install: sudo apt install ripgrep || brew install ripgrep" ;;
                    jq)  echo "         -> install: sudo apt install jq || brew install jq" ;;
                    git) echo "         -> install: sudo apt install git || brew install git" ;;
                esac
            else
                echo "  [FAIL] ${detail}"
            fi
        fi
    done
    echo ""
    echo "=== Summary: ${PASS} passed, ${WARN} warnings, ${FAIL} failed ==="
fi

[ "$FAIL" -gt 0 ] && exit 1
exit 0
