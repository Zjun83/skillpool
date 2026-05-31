#!/usr/bin/env bash
# upgrade-from-skill.sh — Sync scaffold-docs templates and scripts from SKILL source
#
# Compares local project files against the scaffold-docs.skill/ templates
# and offers to update them. Respects MANUAL sections (preserve on upgrade).
# Supports dry-run mode and version checking.
#
# Usage:
#   scripts/upgrade-from-skill.sh [--dry-run] [--force] [SKILL_PATH]
#   scripts/upgrade-from-skill.sh                     # auto-detect skill path
#   scripts/upgrade-from-skill.sh --dry-run           # preview changes only
#   scripts/upgrade-from-skill.sh --force             # overwrite without prompting
#   scripts/upgrade-from-skill.sh /path/to/scaffold-docs.skill

set -euo pipefail

DRY_RUN=false
FORCE=false
SKILL_PATH=""
UPGRADED=0
SKIPPED=0
PRESERVED=0

# ─── Parse arguments ───

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --force)   FORCE=true; shift ;;
        -*)
            echo "Unknown option: $1" >&2
            echo "Usage: upgrade-from-skill.sh [--dry-run] [--force] [SKILL_PATH]" >&2
            exit 1
            ;;
        *)  SKILL_PATH="$1"; shift ;;
    esac
done

# ─── Locate scaffold-docs.skill ───

if [ -z "$SKILL_PATH" ]; then
    # Search common locations
    CANDIDATES=(
        "./scaffold-docs.skill"
        "../scaffold-docs.skill"
        "./.skills/scaffold-docs.skill"
    )

    # Also check SKILL_PATH environment variable
    if [ -n "${SKILLPOOL_SKILL_PATH:-}" ]; then
        CANDIDATES+=("${SKILLPOOL_SKILL_PATH}/scaffold-docs.skill")
    fi

    # Check SkillPool default location
    if [ -n "${SKILLPOOL_HOME:-}" ]; then
        CANDIDATES+=("${SKILLPOOL_HOME}/scaffold-docs.skill")
    fi

    for candidate in "${CANDIDATES[@]}"; do
        if [ -d "$candidate" ]; then
            SKILL_PATH="$candidate"
            break
        fi
    done
fi

if [ -z "$SKILL_PATH" ] || [ ! -d "$SKILL_PATH" ]; then
    echo "[upgrade] Cannot locate scaffold-docs.skill directory" >&2
    echo "  Specify path: upgrade-from-skill.sh /path/to/scaffold-docs.skill" >&2
    echo "  Or set env: SKILLPOOL_SKILL_PATH=/path/to/skillpool" >&2
    exit 1
fi

if [ ! -f "${SKILL_PATH}/skill.yaml" ]; then
    echo "[upgrade] Invalid skill directory: ${SKILL_PATH} (missing skill.yaml)" >&2
    exit 1
fi

# ─── Read current skill version ───

SKILL_VERSION=$(grep -m1 '^  version:' "${SKILL_PATH}/skill.yaml" 2>/dev/null | sed 's/.*version: *//' | tr -d '"' || echo "unknown")
echo "[upgrade] scaffold-docs v${SKILL_VERSION} at ${SKILL_PATH}"
echo ""

# ─── Define files to upgrade ───

# Template files -> project root
TEMPLATE_FILES=(
    "AGENTS.md"
    "PROJECT_ATLAS.md"
    "CODE_MAP.md"
    "DOC_MAP.md"
    "TASK_MAP.md"
    "AGENTS_HANDBOOK.md"
)

# Script files -> scripts/ directory
SCRIPT_FILES=(
    "health-check.sh"
    "gen-code-map.sh"
    "gen_code_map_py.py"
    "refresh-all-docs.sh"
    "validate-links.sh"
    "check-doc-staleness.sh"
    "upgrade-from-skill.sh"
)

# ─── Helper: preserve MANUAL sections from existing file ───

preserve_manual_sections() {
    local old_file="$1"
    local new_content="$2"

    if [ ! -f "$old_file" ]; then
        echo "$new_content"
        return
    fi

    # Extract MANUAL sections from old file
    local manual_sections
    manual_sections=$(grep -zoP '<!--\s*MANUAL\s+START\s*-->.*?<!--\s*MANUAL\s+END\s*-->' "$old_file" 2>/dev/null || true)

    if [ -z "$manual_sections" ]; then
        # No manual sections — return new content with old content as LEGACY
        local old_content
        old_content=$(cat "$old_file")
        echo "${new_content}

<!-- LEGACY START -->
${old_content}
<!-- LEGACY END -->"
        return
    fi

    # New content with manual sections re-injected
    echo "${new_content}"
}

# ─── Helper: compare versions ───

version_lt() {
    local v1="$1" v2="$2"
    # Returns true if v1 < v2
    local sorted
    sorted=$(printf '%s\n%s' "$v1" "$v2" | sort -V | head -1)
    [ "$sorted" = "$v1" ] && [ "$v1" != "$v2" ]
}

# ─── Upgrade template files ───

echo "[1/2] Checking template files ..."

for tpl_name in "${TEMPLATE_FILES[@]}"; do
    tpl_src="${SKILL_PATH}/templates/${tpl_name}.tpl"
    local_file="${tpl_name}"

    if [ ! -f "$tpl_src" ]; then
        echo "  [SKIP] ${tpl_name}: template not found in skill"
        SKIPPED=$((SKIPPED+1))
        continue
    fi

    if [ ! -f "$local_file" ]; then
        # File doesn't exist locally — create it
        echo "  [NEW]   ${tpl_name}: creating from template"
        if [ "$DRY_RUN" = false ]; then
            # Note: template still has {{VAR}} placeholders — user must run main.py for full render
            cp "$tpl_src" "$local_file"
        fi
        UPGRADED=$((UPGRADED+1))
        continue
    fi

    # Check if local version is older than skill version
    local_ver=$(grep -m1 '^version:' "$local_file" 2>/dev/null | sed 's/version: *//' | tr -d '"' || echo "0.0")
    skill_ver=$(grep -m1 '^version:' "$tpl_src" 2>/dev/null | sed 's/version: *//' | tr -d '"' || echo "0.0")

    if [ "$FORCE" = true ] || version_lt "$local_ver" "$skill_ver"; then
        echo "  [UPGRADE] ${tpl_name}: ${local_ver} -> ${skill_ver}"
        if [ "$DRY_RUN" = false ]; then
            if [ "$FORCE" = true ]; then
                # Backup and overwrite
                cp "$local_file" "${local_file}.bak"
                cp "$tpl_src" "$local_file"
            else
                # Preserve MANUAL sections
                new_content=$(cat "$tpl_src")
                merged=$(preserve_manual_sections "$local_file" "$new_content")
                echo "$merged" > "$local_file"
                PRESERVED=$((PRESERVED+1))
            fi
        fi
        UPGRADED=$((UPGRADED+1))
    else
        echo "  [OK]    ${tpl_name}: up-to-date (${local_ver})"
        SKIPPED=$((SKIPPED+1))
    fi
done

echo ""

# ─── Upgrade script files ───

echo "[2/2] Checking script files ..."

mkdir -p scripts

for script_name in "${SCRIPT_FILES[@]}"; do
    script_src="${SKILL_PATH}/scripts/${script_name}"
    local_file="scripts/${script_name}"

    if [ ! -f "$script_src" ]; then
        echo "  [SKIP] ${script_name}: not found in skill"
        SKIPPED=$((SKIPPED+1))
        continue
    fi

    if [ ! -f "$local_file" ]; then
        echo "  [NEW]   ${script_name}: installing"
        if [ "$DRY_RUN" = false ]; then
            cp "$script_src" "$local_file"
            chmod +x "$local_file"
        fi
        UPGRADED=$((UPGRADED+1))
        continue
    fi

    # Compare by checksum
    local_sum=$(sha256sum "$local_file" 2>/dev/null | cut -d' ' -f1 || echo "none")
    skill_sum=$(sha256sum "$script_src" 2>/dev/null | cut -d' ' -f1 || echo "none")

    if [ "$local_sum" != "$skill_sum" ]; then
        if [ "$FORCE" = true ]; then
            echo "  [UPGRADE] ${script_name}: updating (forced)"
            if [ "$DRY_RUN" = false ]; then
                cp "$script_src" "$local_file"
                chmod +x "$local_file"
            fi
            UPGRADED=$((UPGRADED+1))
        else
            echo "  [DIFF]  ${script_name}: differs from skill version (use --force to update)"
            SKIPPED=$((SKIPPED+1))
        fi
    else
        echo "  [OK]    ${script_name}: matches skill version"
        SKIPPED=$((SKIPPED+1))
    fi
done

# ─── Also update symbol-index.json template if present ───

sym_tpl="${SKILL_PATH}/templates/symbol-index.json.tpl"
if [ -f "$sym_tpl" ]; then
    local_sym="docs/symbol-index.json"
    if [ ! -f "$local_sym" ]; then
        echo ""
        echo "  [NOTE]  docs/symbol-index.json not found — run gen-code-map.sh to generate"
    fi
fi

# ─── Summary ───

echo ""
echo "=== Upgrade Summary ==="
echo "  Upgraded: ${UPGRADED}"
echo "  Skipped:  ${SKIPPED}"
echo "  Preserved MANUAL sections: ${PRESERVED}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "(dry run — no files were modified)"
fi

if [ "$UPGRADED" -gt 0 ] && [ "$DRY_RUN" = false ]; then
    echo "Next steps:"
    echo "  1. Review updated files, especially any merge conflicts in MANUAL sections"
    echo "  2. Run 'scripts/health-check.sh' to verify environment"
    echo "  3. Run 'scripts/refresh-all-docs.sh' to regenerate auto-refreshable content"
    echo "  4. Commit changes with: git add -A && git commit -m 'chore: upgrade scaffold-docs to v${SKILL_VERSION}'"
fi

exit 0
