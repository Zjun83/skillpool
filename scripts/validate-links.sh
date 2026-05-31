#!/usr/bin/env bash
# validate-links.sh — Validate internal Markdown links in project documentation
#
# Scans all .md files for [text](relative/path) links and checks that
# the target file or anchor exists. Reports broken links with file:line.
#
# Usage:
#   scripts/validate-links.sh [DOC_ROOT]
#   scripts/validate-links.sh .           # scan current directory
#   scripts/validate-links.sh docs/       # scan docs/ only
#   scripts/validate-links.sh --json .    # JSON output

set -euo pipefail

DOC_ROOT="${1:-.}"
JSON_MODE=false
BROKEN=0
VALID=0
TOTAL=0

# Parse --json flag
if [ "${1:-}" = "--json" ]; then
    JSON_MODE=true
    DOC_ROOT="${2:-.}"
fi

if [ ! -d "$DOC_ROOT" ]; then
    echo "[validate-links] Directory not found: $DOC_ROOT" >&2
    exit 1
fi

# ─── Helper: extract links from a Markdown file ───

extract_links() {
    local file="$1"
    # Match [text](path) — capture the path portion
    # Skip external URLs (http://, https://, ftp://, mailto:)
    # Skip anchor-only links (#anchor)
    grep -noP '\[[^\]]*\]\(([^)]+)\)' "$file" 2>/dev/null | \
    while IFS= read -r match; do
        # Extract line number and link target
        line_num=$(echo "$match" | cut -d: -f1)
        target=$(echo "$match" | sed -E 's/.*\]\(([^)]+)\).*/\1/')

        # Skip external URLs
        case "$target" in
            http://*|https://*|ftp://*|mailto://*) continue ;;
        esac

        # Skip anchor-only links (we validate anchors separately)
        if [ "$target" = "${target#\#}" ]; then
            # Has a path component (not just #anchor)
            # Split path and anchor
            path_part="${target%%#*}"
            anchor_part="${target#*#}"
            if [ "$anchor_part" = "$target" ]; then
                anchor_part=""
            fi
        else
            # Pure anchor link: #something
            path_part=""
            anchor_part="${target#\#}"
        fi

        echo "${line_num}|${path_part}|${anchor_part}"
    done
}

# ─── Helper: resolve path relative to the Markdown file ───

resolve_path() {
    local md_file="$1"
    local rel_path="$2"
    local md_dir
    md_dir="$(dirname "$md_file")"

    # Handle absolute paths (starting with /)
    if [ "${rel_path:0:1}" = "/" ]; then
        echo "${DOC_ROOT}${rel_path}"
        return
    fi

    # Resolve relative path
    local resolved
    resolved="$(cd "$md_dir" 2>/dev/null && realpath --relative-to="$DOC_ROOT" "$rel_path" 2>/dev/null || echo "")"
    if [ -n "$resolved" ]; then
        echo "${DOC_ROOT}/${resolved}"
    else
        # Fallback: simple join
        echo "${md_dir}/${rel_path}"
    fi
}

# ─── Helper: check if anchor exists in a file ───

check_anchor() {
    local file="$1"
    local anchor="$2"

    if [ -z "$anchor" ]; then
        return 0  # No anchor to check
    fi

    # Convert anchor to grep pattern: lowercase, spaces->hyphens, strip punctuation
    local pattern
    pattern=$(echo "$anchor" | tr '[:upper:]' '[:lower:]' | sed 's/  */-/g; s/[^a-z0-9-]//g')

    # Check for GitHub-flavored Markdown heading anchors
    grep -qiE "^#+ .*$pattern" "$file" 2>/dev/null && return 0
    # Check for explicit anchor: <a id="anchor">
    grep -qiE "<a [^>]*id=\"?$pattern\"?" "$file" 2>/dev/null && return 0

    return 1
}

# ─── Main: scan all Markdown files ───

BROKEN_ENTRIES=()

# Collect all .md files
mapfile -t MD_FILES < <(find "$DOC_ROOT" -name "*.md" -not -path "*/.git/*" -not -path "*/node_modules/*" -not -path "*/.scaffold-docs/*" 2>/dev/null | sort)

for md_file in "${MD_FILES[@]}"; do
    [ -f "$md_file" ] || continue

    while IFS='|' read -r line_num path_part anchor_part; do
        [ -z "$line_num" ] && continue
        TOTAL=$((TOTAL+1))

        # Pure anchor link — check within the same file
        if [ -z "$path_part" ]; then
            if check_anchor "$md_file" "$anchor_part"; then
                VALID=$((VALID+1))
            else
                BROKEN=$((BROKEN+1))
                rel_file="${md_file#$DOC_ROOT/}"
                BROKEN_ENTRIES+=("${rel_file}:${line_num} -> #${anchor_part} (anchor not found)")
            fi
            continue
        fi

        # Resolve the target path
        resolved=$(resolve_path "$md_file" "$path_part")

        if [ -f "$resolved" ]; then
            # File exists — check anchor if present
            if [ -n "$anchor_part" ]; then
                if check_anchor "$resolved" "$anchor_part"; then
                    VALID=$((VALID+1))
                else
                    BROKEN=$((BROKEN+1))
                    rel_file="${md_file#$DOC_ROOT/}"
                    BROKEN_ENTRIES+=("${rel_file}:${line_num} -> ${path_part}#${anchor_part} (anchor not found)")
                fi
            else
                VALID=$((VALID+1))
            fi
        else
            BROKEN=$((BROKEN+1))
            rel_file="${md_file#$DOC_ROOT/}"
            BROKEN_ENTRIES+=("${rel_file}:${line_num} -> ${path_part} (file not found)")
        fi
    done < <(extract_links "$md_file")
done

# ─── Output ───

if [ "$JSON_MODE" = true ]; then
    python3 -c "
import json
broken = '''$(printf '%s\n' "${BROKEN_ENTRIES[@]}")'''.strip().split('\n') if ${BROKEN} > 0 else []
print(json.dumps({
    'total': ${TOTAL},
    'valid': ${VALID},
    'broken': ${BROKEN},
    'broken_links': [b for b in broken if b]
}, indent=2))
"
else
    echo "=== Link Validation Report ==="
    echo ""
    if [ "$BROKEN" -gt 0 ]; then
        echo "Broken links (${BROKEN}):"
        for entry in "${BROKEN_ENTRIES[@]}"; do
            echo "  [BROKEN] $entry"
        done
    else
        echo "All links valid."
    fi
    echo ""
    echo "Total: ${TOTAL} | Valid: ${VALID} | Broken: ${BROKEN}"
fi

[ "$BROKEN" -gt 0 ] && exit 1
exit 0
