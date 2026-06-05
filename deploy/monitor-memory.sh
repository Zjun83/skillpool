#!/bin/bash
# deploy/monitor-memory.sh — Check MCP service RSS vs cgroup limits
# Usage: ./monitor-memory.sh [--json]
set -euo pipefail

THRESHOLD_PCT=80
JSON_OUTPUT=false
[[ "${1:-}" == "--json" ]] && JSON_OUTPUT=true

SERVICES=(
  skillpool-mcp-http
  clawmem-mcp
  agent-search-mcp
  codex-guard-mcp
)

alerts=0
results=()

for svc in "${SERVICES[@]}"; do
  pid=$(systemctl --user show "$svc" 2>/dev/null | grep "^MainPID=" | cut -d= -f2 || echo "0")
  if [[ "$pid" -eq 0 ]]; then
    results+=("$svc: NOT RUNNING")
    continue
  fi

  rss_kb=$(ps -o rss= -p "$pid" 2>/dev/null || echo "0")
  rss_mb=$((rss_kb / 1024))

  limit_bytes=$(systemctl --user show "$svc" 2>/dev/null | grep "^MemoryHigh=" | cut -d= -f2 || echo "0")
  if [[ "$limit_bytes" -gt 0 ]]; then
    limit_mb=$((limit_bytes / 1048576))
    pct=$((rss_mb * 100 / limit_mb))
    if [[ "$pct" -gt "$THRESHOLD_PCT" ]]; then
      results+=("WARN: $svc RSS=${rss_mb}MB > ${THRESHOLD_PCT}% of limit=${limit_mb}MB (${pct}%)")
      ((alerts++)) || true
    else
      results+=("OK: $svc RSS=${rss_mb}MB / ${limit_mb}MB (${pct}%)")
    fi
  else
    results+=("INFO: $svc RSS=${rss_mb}MB (no limit)")
  fi
done

if $JSON_OUTPUT; then
  echo "{\"alerts\": $alerts, \"results\": [$(printf '"%s",' "${results[@]}" | sed 's/,$//')]}"
else
  for r in "${results[@]}"; do
    echo "$r"
  done
  if [[ "$alerts" -gt 0 ]]; then
    echo "--- $alerts alert(s) above ${THRESHOLD_PCT}% threshold ---"
  else
    echo "--- All services within ${THRESHOLD_PCT}% of limits ---"
  fi
fi

exit $alerts
