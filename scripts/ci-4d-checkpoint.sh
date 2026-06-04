#!/usr/bin/env bash
# ci-4d-checkpoint.sh — Validate 4D paradigm phase transitions for CI
#
# Validates that code changes follow the 4D paradigm (DocsDD→SDD→BDD→TDD)
# by checking gate.json state and enforcing phase transitions.
#
# Usage:
#   ci-4d-checkpoint.sh --complexity L1 [--state-path path] [--json]
#   ci-4d-checkpoint.sh --complexity L2 [--state-path path] [--json]
#   ci-4d-checkpoint.sh --complexity L3 [--state-path path] [--json]
#   ci-4d-checkpoint.sh --complexity L0 [--state-path path] [--json]
#
# Exit codes:
#   0 — Validation passed
#   1 — Validation failed
#   2 — Invalid arguments or missing dependencies
#
# Part of SkillPool — independent infrastructure

set -euo pipefail

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

readonly SCRIPT_NAME="$(basename "$0")"
readonly VALID_PHASES="IDLE ASSESSING DOCSDD SDD BDD TDD REVIEW COMPLETE"
readonly VALID_LEVELS="L0 L1 L2 L3"

# Phase order for transition validation
declare -A PHASE_ORDER=(
    ["IDLE"]=0
    ["ASSESSING"]=1
    ["DOCSDD"]=2
    ["SDD"]=3
    ["BDD"]=4
    ["TDD"]=5
    ["REVIEW"]=6
    ["COMPLETE"]=7
)

# Legal transitions (from -> allowed targets)
declare -A LEGAL_TRANSITIONS=(
    ["IDLE"]="ASSESSING"
    ["ASSESSING"]="COMPLETE DOCSDD SDD"
    ["DOCSDD"]="SDD"
    ["SDD"]="BDD TDD"
    ["BDD"]="TDD"
    ["TDD"]="REVIEW COMPLETE"
    ["REVIEW"]="COMPLETE"
    ["COMPLETE"]=""
)

# Level conditions for transitions (from,to -> required levels)
declare -A TRANSITION_LEVEL_CONDITIONS=(
    ["ASSESSING,COMPLETE"]="L0"
    ["ASSESSING,DOCSDD"]="L2 L3+L2+"
    ["ASSESSING,SDD"]="L1 L2 L3+L2+"
    ["SDD,BDD"]="L2 L3+L2+"
    ["SDD,TDD"]="L1"
    ["TDD,REVIEW"]="L3+L2+"
    ["TDD,COMPLETE"]="L0 L1 L2"
)

# -----------------------------------------------------------------------------
# Global state
# -----------------------------------------------------------------------------

COMPLEXITY_LEVEL=""
STATE_PATH=""
JSON_OUTPUT=false
GATE_DATA=""

# -----------------------------------------------------------------------------
# Logging helpers
# -----------------------------------------------------------------------------

log_error() {
    echo "ERROR: $*" >&2
}

log_info() {
    if [[ "$JSON_OUTPUT" == "false" ]]; then
        echo "INFO: $*"
    fi
}

log_debug() {
    if [[ "$JSON_OUTPUT" == "false" ]]; then
        echo "DEBUG: $*"
    fi
}

# -----------------------------------------------------------------------------
# JSON output helpers
# -----------------------------------------------------------------------------

json_escape() {
    local str="$1"
    str="${str//\\/\\\\}"
    str="${str//\"/\\\"}"
    str="${str//$'\n'/\\n}"
    str="${str//$'\r'/\\r}"
    str="${str//$'\t'/\\t}"
    echo "$str"
}

output_json_result() {
    local status="$1"
    local message="$2"
    local current_phase="$3"
    local assessed_level="$4"
    local phase_history="$5"
    local review_triggered="$6"
    local errors="$7"

    local escaped_message
    local escaped_errors
    escaped_message=$(json_escape "$message")
    escaped_errors=$(json_escape "$errors")

    cat <<EOF
{
  "status": "$status",
  "message": "$escaped_message",
  "current_phase": "$current_phase",
  "assessed_level": "$assessed_level",
  "phase_history": $phase_history,
  "review_checkpoint": {
    "triggered": $review_triggered
  },
  "errors": "$escaped_errors"
}
EOF
}

# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME --complexity LEVEL [OPTIONS]

Validate 4D paradigm phase transitions for CI.

Required:
  --complexity LEVEL      Expected complexity level (L0, L1, L2, L3)
                          L3 maps to L3+L2+ internally

Options:
  --state-path PATH       Path to gate.json file (default: ./gate.json)
  --json                  Output in JSON format for machine parsing
  -h, --help              Show this help message

Complexity level requirements:
  L0  — No gate.json needed (direct edit, auto-complete)
  L1  — SDD→TDD phases completed (skip DocsDD/BDD)
  L2  — All 4 phases completed (DocsDD→SDD→BDD→TDD)
  L3  — All 4 phases + REVIEW checkpoint triggered

Examples:
  $SCRIPT_NAME --complexity L1
  $SCRIPT_NAME --complexity L2 --state-path /tmp/gate.json
  $SCRIPT_NAME --complexity L3 --json

Exit codes:
  0 — Validation passed
  1 — Validation failed
  2 — Invalid arguments or missing dependencies
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --complexity)
                if [[ -z "${2:-}" ]]; then
                    log_error "--complexity requires a level argument"
                    exit 2
                fi
                COMPLEXITY_LEVEL="$2"
                shift 2
                ;;
            --state-path)
                if [[ -z "${2:-}" ]]; then
                    log_error "--state-path requires a path argument"
                    exit 2
                fi
                STATE_PATH="$2"
                shift 2
                ;;
            --json)
                JSON_OUTPUT=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 2
                ;;
        esac
    done

    # Validate required arguments
    if [[ -z "$COMPLEXITY_LEVEL" ]]; then
        log_error "--complexity is required"
        usage
        exit 2
    fi

    # Validate complexity level
    if [[ ! " $VALID_LEVELS " =~ " $COMPLEXITY_LEVEL " ]]; then
        log_error "Invalid complexity level: $COMPLEXITY_LEVEL (valid: L0, L1, L2, L3)"
        exit 2
    fi

    # Default state path
    if [[ -z "$STATE_PATH" ]]; then
        STATE_PATH="./gate.json"
    fi
}

# -----------------------------------------------------------------------------
# Gate state reading
# -----------------------------------------------------------------------------

# Try to read gate state via skillpool CLI, fallback to direct file read
read_gate_state() {
    local gate_content=""

    # Try skillpool CLI first
    if command -v skillpool &>/dev/null; then
        log_debug "Attempting to read gate state via skillpool CLI"
        gate_content=$(skillpool gate status --state-path "$STATE_PATH" 2>/dev/null || true)
        if [[ -n "$gate_content" ]]; then
            log_debug "Got gate state from CLI"
            # CLI output is human-readable, we still need the JSON file
        fi
    fi

    # Read gate.json directly
    if [[ -f "$STATE_PATH" ]]; then
        log_debug "Reading gate.json from: $STATE_PATH"
        GATE_DATA=$(cat "$STATE_PATH")
        return 0
    else
        return 1
    fi
}

# Extract a field from gate.json using jq or grep fallback
extract_field() {
    local field="$1"
    local data="${2:-$GATE_DATA}"

    if command -v jq &>/dev/null; then
        echo "$data" | jq -r ".$field // empty" 2>/dev/null || echo ""
    else
        # Fallback: simple grep-based extraction
        echo "$data" | grep -o "\"$field\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | \
            sed "s/\"$field\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\"/\\1/" | head -1 || echo ""
    fi
}

# Extract boolean field
extract_bool() {
    local field="$1"
    local data="${2:-$GATE_DATA}"

    if command -v jq &>/dev/null; then
        echo "$data" | jq -r ".$field // false" 2>/dev/null || echo "false"
    else
        # Fallback: grep for true/false
        local val
        val=$(echo "$data" | grep -o "\"$field\"[[:space:]]*:[[:space:]]*[a-z]*" | \
              sed "s/\"$field\"[[:space:]]*:[[:space:]]*//" | head -1 || echo "false")
        echo "$val"
    fi
}

# Extract array length
extract_array_length() {
    local field="$1"
    local data="${2:-$GATE_DATA}"

    if command -v jq &>/dev/null; then
        echo "$data" | jq -r ".${field} | length // 0" 2>/dev/null || echo "0"
    else
        # Fallback: count array elements (rough approximation)
        echo "$data" | grep -o "\"$field\"[[:space:]]*:[[:space:]]*\\[" -A 100 | \
            grep -c '"from_phase"' || echo "0"
    fi
}

# Extract phase history as JSON array
extract_phase_history_json() {
    local data="${1:-$GATE_DATA}"

    if command -v jq &>/dev/null; then
        echo "$data" | jq -c '.phase_history // []' 2>/dev/null || echo "[]"
    else
        # Fallback: return empty array
        echo "[]"
    fi
}

# -----------------------------------------------------------------------------
# Validation functions
# -----------------------------------------------------------------------------

validate_l0() {
    # L0: Direct edit, no gate.json needed
    # If gate.json exists, it should be in COMPLETE state (auto-completed)
    log_info "Validating L0 (direct edit) requirements..."

    if [[ ! -f "$STATE_PATH" ]]; then
        log_info "L0: No gate.json found — acceptable for direct edits"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            output_json_result "pass" "L0: No gate.json required for direct edits" "N/A" "L0" "[]" "false" ""
        fi
        return 0
    fi

    # gate.json exists, read it and check if it's COMPLETE
    GATE_DATA=$(cat "$STATE_PATH")
    local current_phase
    current_phase=$(extract_field "current_phase")

    if [[ "$current_phase" == "COMPLETE" ]]; then
        log_info "L0: gate.json in COMPLETE state — valid"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "pass" "L0: gate.json in COMPLETE state" "$current_phase" "L0" "$history" "false" ""
        fi
        return 0
    fi

    log_error "L0: gate.json exists but not in COMPLETE state (current: $current_phase)"
    if [[ "$JSON_OUTPUT" == "true" ]]; then
        local history
        history=$(extract_phase_history_json)
        output_json_result "fail" "L0: gate.json not in COMPLETE state" "$current_phase" "L0" "$history" "false" "Expected COMPLETE, got $current_phase"
    fi
    return 1
}

validate_l1() {
    # L1: SDD→TDD phases completed (skip DocsDD/BDD)
    # Valid paths:
    #   ASSESSING → SDD → TDD → COMPLETE
    #   ASSESSING → SDD → TDD (if still in TDD, that's also valid for checkpoint)
    log_info "Validating L1 (SDD→TDD) requirements..."

    local current_phase assessed_level
    current_phase=$(extract_field "current_phase")
    assessed_level=$(extract_field "assessed_level")

    # Check assessed level matches
    if [[ -n "$assessed_level" && "$assessed_level" != "L1" ]]; then
        log_error "L1: assessed_level mismatch (expected L1, got $assessed_level)"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L1: assessed_level mismatch" "$current_phase" "$assessed_level" "$history" "false" "Expected L1, got $assessed_level"
        fi
        return 1
    fi

    # Valid end states for L1: TDD or COMPLETE
    if [[ "$current_phase" != "TDD" && "$current_phase" != "COMPLETE" ]]; then
        log_error "L1: Invalid end state (expected TDD or COMPLETE, got $current_phase)"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L1: Invalid end state" "$current_phase" "$assessed_level" "$history" "false" "Expected TDD or COMPLETE, got $current_phase"
        fi
        return 1
    fi

    # Validate phase history contains required transitions
    local has_assessing_to_sdd=0
    local has_sdd_to_tdd=0

    if command -v jq &>/dev/null; then
        has_assessing_to_sdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "ASSESSING" and .to_phase == "SDD")] | length' 2>/dev/null || echo "0")
        has_sdd_to_tdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "SDD" and .to_phase == "TDD")] | length' 2>/dev/null || echo "0")
    else
        # Fallback: grep-based check
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"ASSESSING"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"SDD"' && has_assessing_to_sdd=1
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"SDD"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"TDD"' && has_sdd_to_tdd=1
    fi

    if [[ "$has_assessing_to_sdd" -eq 0 ]]; then
        log_error "L1: Missing required transition ASSESSING → SDD"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L1: Missing ASSESSING→SDD transition" "$current_phase" "$assessed_level" "$history" "false" "Missing ASSESSING → SDD"
        fi
        return 1
    fi

    if [[ "$has_sdd_to_tdd" -eq 0 ]]; then
        log_error "L1: Missing required transition SDD → TDD"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L1: Missing SDD→TDD transition" "$current_phase" "$assessed_level" "$history" "false" "Missing SDD → TDD"
        fi
        return 1
    fi

    log_info "L1: Validation passed (SDD→TDD path complete)"
    if [[ "$JSON_OUTPUT" == "true" ]]; then
        local history
        history=$(extract_phase_history_json)
        output_json_result "pass" "L1: SDD→TDD path validated" "$current_phase" "$assessed_level" "$history" "false" ""
    fi
    return 0
}

validate_l2() {
    # L2: All 4 phases completed (DocsDD→SDD→BDD→TDD)
    # Valid path: ASSESSING → DOCSDD → SDD → BDD → TDD → COMPLETE
    log_info "Validating L2 (DocsDD→SDD→BDD→TDD) requirements..."

    local current_phase assessed_level
    current_phase=$(extract_field "current_phase")
    assessed_level=$(extract_field "assessed_level")

    # Check assessed level matches (L2 or L3+L2+)
    if [[ -n "$assessed_level" && "$assessed_level" != "L2" && "$assessed_level" != "L3+L2+" ]]; then
        log_error "L2: assessed_level mismatch (expected L2 or L3+L2+, got $assessed_level)"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L2: assessed_level mismatch" "$current_phase" "$assessed_level" "$history" "false" "Expected L2 or L3+L2+, got $assessed_level"
        fi
        return 1
    fi

    # Valid end states for L2: TDD or COMPLETE
    if [[ "$current_phase" != "TDD" && "$current_phase" != "COMPLETE" ]]; then
        log_error "L2: Invalid end state (expected TDD or COMPLETE, got $current_phase)"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L2: Invalid end state" "$current_phase" "$assessed_level" "$history" "false" "Expected TDD or COMPLETE, got $current_phase"
        fi
        return 1
    fi

    # Validate phase history contains all 4D transitions
    local has_assessing_to_docsdd=0
    local has_docsdd_to_sdd=0
    local has_sdd_to_bdd=0
    local has_bdd_to_tdd=0

    if command -v jq &>/dev/null; then
        has_assessing_to_docsdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "ASSESSING" and .to_phase == "DOCSDD")] | length' 2>/dev/null || echo "0")
        has_docsdd_to_sdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "DOCSDD" and .to_phase == "SDD")] | length' 2>/dev/null || echo "0")
        has_sdd_to_bdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "SDD" and .to_phase == "BDD")] | length' 2>/dev/null || echo "0")
        has_bdd_to_tdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "BDD" and .to_phase == "TDD")] | length' 2>/dev/null || echo "0")
    else
        # Fallback: grep-based checks
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"ASSESSING"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"DOCSDD"' && has_assessing_to_docsdd=1
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"DOCSDD"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"SDD"' && has_docsdd_to_sdd=1
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"SDD"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"BDD"' && has_sdd_to_bdd=1
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"BDD"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"TDD"' && has_bdd_to_tdd=1
    fi

    local missing_transitions=""

    if [[ "$has_assessing_to_docsdd" -eq 0 ]]; then
        missing_transitions="$missing_transitions ASSESSING→DOCSDD"
    fi
    if [[ "$has_docsdd_to_sdd" -eq 0 ]]; then
        missing_transitions="$missing_transitions DOCSDD→SDD"
    fi
    if [[ "$has_sdd_to_bdd" -eq 0 ]]; then
        missing_transitions="$missing_transitions SDD→BDD"
    fi
    if [[ "$has_bdd_to_tdd" -eq 0 ]]; then
        missing_transitions="$missing_transitions BDD→TDD"
    fi

    if [[ -n "$missing_transitions" ]]; then
        log_error "L2: Missing required transitions:$missing_transitions"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L2: Missing 4D transitions" "$current_phase" "$assessed_level" "$history" "false" "Missing:$missing_transitions"
        fi
        return 1
    fi

    log_info "L2: Validation passed (DocsDD→SDD→BDD→TDD path complete)"
    if [[ "$JSON_OUTPUT" == "true" ]]; then
        local history
        history=$(extract_phase_history_json)
        output_json_result "pass" "L2: Full 4D path validated" "$current_phase" "$assessed_level" "$history" "false" ""
    fi
    return 0
}

validate_l3() {
    # L3: All 4 phases + REVIEW checkpoint triggered
    # Valid path: ASSESSING → DOCSDD → SDD → BDD → TDD → REVIEW → COMPLETE
    log_info "Validating L3 (4D + REVIEW) requirements..."

    local current_phase assessed_level review_triggered
    current_phase=$(extract_field "current_phase")
    assessed_level=$(extract_field "assessed_level")
    review_triggered=$(extract_bool "review_checkpoint.triggered")

    # Check assessed level matches (must be L3+L2+)
    if [[ -n "$assessed_level" && "$assessed_level" != "L3+L2+" ]]; then
        log_error "L3: assessed_level mismatch (expected L3+L2+, got $assessed_level)"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L3: assessed_level mismatch" "$current_phase" "$assessed_level" "$history" "$review_triggered" "Expected L3+L2+, got $assessed_level"
        fi
        return 1
    fi

    # Valid end states for L3: REVIEW or COMPLETE
    if [[ "$current_phase" != "REVIEW" && "$current_phase" != "COMPLETE" ]]; then
        log_error "L3: Invalid end state (expected REVIEW or COMPLETE, got $current_phase)"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L3: Invalid end state" "$current_phase" "$assessed_level" "$history" "$review_triggered" "Expected REVIEW or COMPLETE, got $current_phase"
        fi
        return 1
    fi

    # Validate phase history contains all 4D transitions + TDD→REVIEW
    local has_assessing_to_docsdd=0
    local has_docsdd_to_sdd=0
    local has_sdd_to_bdd=0
    local has_bdd_to_tdd=0
    local has_tdd_to_review=0

    if command -v jq &>/dev/null; then
        has_assessing_to_docsdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "ASSESSING" and .to_phase == "DOCSDD")] | length' 2>/dev/null || echo "0")
        has_docsdd_to_sdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "DOCSDD" and .to_phase == "SDD")] | length' 2>/dev/null || echo "0")
        has_sdd_to_bdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "SDD" and .to_phase == "BDD")] | length' 2>/dev/null || echo "0")
        has_bdd_to_tdd=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "BDD" and .to_phase == "TDD")] | length' 2>/dev/null || echo "0")
        has_tdd_to_review=$(echo "$GATE_DATA" | jq '[.phase_history[] | select(.from_phase == "TDD" and .to_phase == "REVIEW")] | length' 2>/dev/null || echo "0")
    else
        # Fallback: grep-based checks
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"ASSESSING"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"DOCSDD"' && has_assessing_to_docsdd=1
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"DOCSDD"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"SDD"' && has_docsdd_to_sdd=1
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"SDD"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"BDD"' && has_sdd_to_bdd=1
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"BDD"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"TDD"' && has_bdd_to_tdd=1
        echo "$GATE_DATA" | grep -q '"from_phase"[[:space:]]*:[[:space:]]*"TDD"' && \
            echo "$GATE_DATA" | grep -q '"to_phase"[[:space:]]*:[[:space:]]*"REVIEW"' && has_tdd_to_review=1
    fi

    local missing_transitions=""

    if [[ "$has_assessing_to_docsdd" -eq 0 ]]; then
        missing_transitions="$missing_transitions ASSESSING→DOCSDD"
    fi
    if [[ "$has_docsdd_to_sdd" -eq 0 ]]; then
        missing_transitions="$missing_transitions DOCSDD→SDD"
    fi
    if [[ "$has_sdd_to_bdd" -eq 0 ]]; then
        missing_transitions="$missing_transitions SDD→BDD"
    fi
    if [[ "$has_bdd_to_tdd" -eq 0 ]]; then
        missing_transitions="$missing_transitions BDD→TDD"
    fi
    if [[ "$has_tdd_to_review" -eq 0 ]]; then
        missing_transitions="$missing_transitions TDD→REVIEW"
    fi

    if [[ -n "$missing_transitions" ]]; then
        log_error "L3: Missing required transitions:$missing_transitions"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L3: Missing 4D+REVIEW transitions" "$current_phase" "$assessed_level" "$history" "$review_triggered" "Missing:$missing_transitions"
        fi
        return 1
    fi

    # Check review checkpoint triggered
    if [[ "$review_triggered" != "true" ]]; then
        log_error "L3: Review checkpoint not triggered"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            local history
            history=$(extract_phase_history_json)
            output_json_result "fail" "L3: Review checkpoint not triggered" "$current_phase" "$assessed_level" "$history" "false" "Review checkpoint must be triggered for L3"
        fi
        return 1
    fi

    log_info "L3: Validation passed (DocsDD→SDD→BDD→TDD→REVIEW path complete)"
    if [[ "$JSON_OUTPUT" == "true" ]]; then
        local history
        history=$(extract_phase_history_json)
        output_json_result "pass" "L3: Full 4D+REVIEW path validated" "$current_phase" "$assessed_level" "$history" "true" ""
    fi
    return 0
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    parse_args "$@"

    log_info "CI 4D Checkpoint Gate"
    log_info "Complexity level: $COMPLEXITY_LEVEL"
    log_info "State path: $STATE_PATH"

    # L0 special case: no gate.json required
    if [[ "$COMPLEXITY_LEVEL" == "L0" ]]; then
        validate_l0
        exit $?
    fi

    # For L1/L2/L3, gate.json must exist
    if ! read_gate_state; then
        log_error "gate.json not found at: $STATE_PATH"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            output_json_result "fail" "gate.json not found" "N/A" "N/A" "[]" "false" "File not found: $STATE_PATH"
        fi
        exit 1
    fi

    # Validate gate.json is valid JSON
    if ! echo "$GATE_DATA" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
        log_error "gate.json is not valid JSON"
        if [[ "$JSON_OUTPUT" == "true" ]]; then
            output_json_result "fail" "gate.json is not valid JSON" "N/A" "N/A" "[]" "false" "Invalid JSON format"
        fi
        exit 1
    fi

    # Run appropriate validation
    case "$COMPLEXITY_LEVEL" in
        L1)
            validate_l1
            ;;
        L2)
            validate_l2
            ;;
        L3)
            validate_l3
            ;;
        *)
            log_error "Unhandled complexity level: $COMPLEXITY_LEVEL"
            exit 2
            ;;
    esac
}

main "$@"
