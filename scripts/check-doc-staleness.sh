#!/usr/bin/env bash
# check-doc-staleness.sh — Three-layer document staleness detection
#
# Layer 1: last_verified date + threshold days -> stale
# Layer 2: git diff since last_verified — commit count exceeds threshold -> possibly stale
# Layer 3: CODE_MAP.md symbol-level verification — symbols in index still exist in source
#
# Usage:
#   scripts/check-doc-staleness.sh [DOC_ROOT] [THRESHOLD_DAYS] [THRESHOLD_COMMITS]
#   scripts/check-doc-staleness.sh . 30 20
#   scripts/check-doc-staleness.sh --json . 30 20

set -euo pipefail

DOC_ROOT="${1:-.}"
THRESHOLD_DAYS="${2:-30}"
THRESHOLD_COMMITS="${3:-20}"
JSON_MODE=false
STALE_FILES=0
FRESH_FILES=0
TOTAL_FILES=0
STALE_ENTRIES=()

# Parse --json flag
if [ "${1:-}" = "--json" ]; then
    JSON_MODE=true
    DOC_ROOT="${2:-.}"
    THRESHOLD_DAYS="${3:-30}"
    THRESHOLD_COMMITS="${4:-20}"
fi

if [ ! -d "$DOC_ROOT" ]; then
    echo "[check-doc-staleness] Directory not found: $DOC_ROOT" >&2
    exit 1
fi

# ─── Helper: parse last_verified from frontmatter ───

get_last_verified() {
    local file="$1"
    grep -m1 '^last_verified:' "$file" 2>/dev/null | \
        sed 's/last_verified: *//' | tr -d '"' | tr -d "'" || echo ""
}

# ─── Helper: calculate days since a date string ───

days_since() {
    local date_str="$1"
    local target_ts
    target_ts=$(date -d "$date_str" +%s 2>/dev/null || echo 0)
    if [ "$target_ts" -eq 0 ]; then
        # Try ISO 8601 format: 2026-05-28T12:00:00Z
        local clean_date
        clean_date=$(echo "$date_str" | sed 's/T/ /; s/Z//; s/+[0-9]*$//')
        target_ts=$(date -d "$clean_date" +%s 2>/dev/null || echo 0)
    fi
    if [ "$target_ts" -eq 0 ]; then
        echo "9999"  # Cannot parse date -> treat as very stale
        return
    fi
    local now_ts
    now_ts=$(date +%s)
    echo $(( (now_ts - target_ts) / 86400 ))
}

# ─── Helper: count git commits since a date ───

commits_since() {
    local date_str="$1"
    local source_dir="${2:-src/}"
    if ! command -v git >/dev/null 2>&1; then
        echo "0"
        return
    fi
    # Check if we're inside a git repo
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "0"
        return
    fi
    local count
    count=$(git log --since="$date_str" --oneline -- "$source_dir" 2>/dev/null | wc -l || echo 0)
    echo "$count"
}

# ─── Helper: Layer 3 — symbol-level verification for CODE_MAP.md ───

check_symbols() {
    local symbol_index="${DOC_ROOT}/docs/symbol-index.json"
    if [ ! -f "$symbol_index" ]; then
        echo "no_index"
        return
    fi

    local missing
    missing=$(python3 -c "
import json, subprocess, sys
try:
    data = json.load(open('${symbol_index}'))
    symbols = data.get('symbols', data) if isinstance(data, dict) else data
    if not isinstance(symbols, list):
        print('parse_error')
        sys.exit(0)
    missing_list = []
    # Sample up to 50 symbols to keep runtime reasonable
    for s in symbols[:50]:
        name = s.get('name', '')
        if not name:
            continue
        try:
            result = subprocess.run(
                ['grep', '-r', '-q', '-w', name, 'src/'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                missing_list.append(name)
        except (subprocess.TimeoutExpired, Exception):
            pass
    if missing_list:
        print(','.join(missing_list[:10]))  # Report up to 10 missing
    else:
        print('')
except (json.JSONDecodeError, OSError) as e:
    print('parse_error')
" 2>/dev/null || echo "error")

    echo "$missing"
}

# ─── Main: scan all .md files ───

mapfile -t MD_FILES < <(find "$DOC_ROOT" -maxdepth 1 -name "*.md" -not -path "*/.git/*" 2>/dev/null | sort)

for md in "${MD_FILES[@]}"; do
    [ -f "$md" ] || continue
    name=$(basename "$md")
    TOTAL_FILES=$((TOTAL_FILES+1))

    last_verified=$(get_last_verified "$md")
    is_stale=false
    stale_reason=""

    # ─── Layer 1: last_verified age check ───

    if [ -n "$last_verified" ]; then
        days=$(days_since "$last_verified")
        if [ "$days" -gt "$THRESHOLD_DAYS" ]; then
            is_stale=true
            stale_reason="last_verified ${days}d ago (>${THRESHOLD_DAYS}d threshold)"
        fi
    else
        # No last_verified field — treat as potentially stale
        is_stale=true
        stale_reason="no last_verified field in frontmatter"
    fi

    # ─── Layer 2: git diff check ───

    if [ "$is_stale" = false ] && [ -n "$last_verified" ]; then
        commits=$(commits_since "$last_verified" "src/")
        if [ "$commits" -gt "$THRESHOLD_COMMITS" ]; then
            is_stale=true
            stale_reason="${commits} commits since last_verified (>${THRESHOLD_COMMITS} threshold)"
        fi
    fi

    # ─── Layer 3: symbol-level check (CODE_MAP.md only) ───

    if [ "$name" = "CODE_MAP.md" ]; then
        missing_symbols=$(check_symbols)
        if [ "$missing_symbols" = "no_index" ]; then
            : # No symbol index to check against
        elif [ "$missing_symbols" = "parse_error" ] || [ "$missing_symbols" = "error" ]; then
            : # Cannot parse index, skip
        elif [ -n "$missing_symbols" ]; then
            is_stale=true
            stale_reason="missing symbols: ${missing_symbols}"
        fi
    fi

    # ─── Report ───

    if [ "$is_stale" = true ]; then
        STALE_FILES=$((STALE_FILES+1))
        STALE_ENTRIES+=("${name}|stale|${stale_reason}")
    else
        FRESH_FILES=$((FRESH_FILES+1))
        STALE_ENTRIES+=("${name}|fresh|")
    fi
done

# ─── Output ───

if [ "$JSON_MODE" = true ]; then
    python3 -c "
import json
entries = []
for e in '''$(printf '%s\n' "${STALE_ENTRIES[@]}")'''.strip().split('\n'):
    parts = e.split('|')
    if len(parts) >= 3:
        entries.append({'file': parts[0], 'status': parts[1], 'reason': parts[2]})
print(json.dumps({
    'total': ${TOTAL_FILES},
    'fresh': ${FRESH_FILES},
    'stale': ${STALE_FILES},
    'threshold_days': ${THRESHOLD_DAYS},
    'threshold_commits': ${THRESHOLD_COMMITS},
    'documents': entries
}, indent=2))
"
else
    echo "=== Document Staleness Report ==="
    echo "  Threshold: ${THRESHOLD_DAYS} days, ${THRESHOLD_COMMITS} commits"
    echo ""

    for entry in "${STALE_ENTRIES[@]}"; do
        IFS='|' read -r name status reason <<< "$entry"
        if [ "$status" = "stale" ]; then
            echo "  [STALE] ${name}: ${reason}"
        else
            echo "  [FRESH] ${name}"
        fi
    done

    echo ""
    echo "=== Summary: ${FRESH_FILES} fresh, ${STALE_FILES} stale (of ${TOTAL_FILES} documents) ==="

    if [ "$STALE_FILES" -gt 0 ]; then
        echo ""
        echo "Actions:"
        echo "  1. Run 'scripts/refresh-all-docs.sh' to update auto-refreshable documents"
        echo "  2. Manually review and update stale documents"
        echo "  3. Update last_verified dates after review: edit frontmatter in each .md file"
    fi
fi

[ "$STALE_FILES" -gt 0 ] && exit 1
exit 0
