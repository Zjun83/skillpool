# WSL2 / Production Resource Planning

> Generated: 2026-06-04 | System: WSL2 (20GB RAM, 8GB Swap)

## 1. Current Resource Profile

| Resource | Total | Used (typical) | Available | Safety Margin |
|----------|-------|----------------|-----------|---------------|
| RAM | 20 GB | 4-6 GB | 14-16 GB | 70-80% |
| Swap | 8 GB | ~0 GB | 8 GB | 99% |
| Disk | 1007 GB | 55 GB | 902 GB | 89% |

## 2. Service Memory Budget

| Service | RSS (MB) | % of 20GB | Category |
|---------|----------|-----------|----------|
| Claude Code (bun) | 1,814 | 8.8% | Core |
| Higress Console | 333 | 1.6% | Infra |
| Hermes Agent | 230 | 1.1% | Agent |
| SkillPool MCP | 194 | 0.9% | Core |
| SearXNG | 98 | 0.5% | Infra |
| Docker Daemon | 80 | 0.4% | Infra |
| ClawMem MCP | 75 | 0.4% | Core |
| Agent-Search MCP | 70 | 0.3% | Core |
| Codex-Guard MCP | 70 | 0.3% | Core |
| ClawMem Server | 53 | 0.3% | Core |
| vMCP Gateway | 52 | 0.3% | Core |
| **Total** | **~3,069** | **15%** | — |

**Headroom**: ~15 GB (75%) at typical load.

## 3. OOM Risk Assessment

### Historical Incident
- HTTP mode SkillPool MCP was OOM-killed at ~15/21GB usage
- Root cause: FastMCP + uvicorn memory leak under sustained load
- Resolution: Switched to stdio transport for production

### Risk Matrix

| Scenario | Est. Memory | OOM Risk | Mitigation |
|----------|-------------|----------|------------|
| Normal operation (all services) | ~4 GB | None | — |
| + Docker build | +1-2 GB | Low | Build in off-peak |
| + Ollama inference (7B) | +4-6 GB | Medium | Use KEEP mode, limit concurrency |
| + Docker container runtime | +0.5 GB | Low | — |
| Stress test (100 concurrent) | +2-3 GB | Medium | Monitor RSS, set ulimit |

### OOM Thresholds

| Level | Condition | Action |
|-------|-----------|--------|
| Green | RSS < 12 GB | Normal operation |
| Yellow | RSS 12-15 GB | Reduce concurrency, stop Docker |
| Red | RSS > 15 GB | Kill non-essential services, restart Ollama |

## 4. Production Recommendations

### 4.1 Memory Limits
```bash
# /etc/security/limits.d/skillpool.conf
skillpool soft rss 4194304   # 4GB soft limit
skillpool hard rss 8388608   # 8GB hard limit
```

### 4.2 Docker Container Limits
```yaml
# docker-compose.yml
deploy:
  resources:
    limits:
      memory: 1G
    reservations:
      memory: 512M
```

### 4.3 WSL2 Config (Windows)
```ini
# %USERPROFILE%/.wslconfig
[wsl2]
memory=16GB        # Cap at 16GB, leave 4GB for Windows
swap=8GB
swapFile=C:\\temp\\wsl-swap.vhdx
```

### 4.4 systemd OOM Protection
```ini
# /etc/systemd/system/skillpool-mcp-http.service
[Service]
OOMPolicy=stop
OOMScoreAdjust=-100
MemoryMax=1G
```

## 5. Monitoring Commands

```bash
# Quick memory check
free -h | awk '/Mem:/{printf "RAM: %.0f%% used\n", $3/$2*100}'

# Top consumers
ps aux --sort=-%mem | head -10

# SkillPool MCP RSS
ps -o rss= -p $(pgrep -f skillpool-mcp) | awk '{printf "%.0f MB\n", $1/1024}'

# Docker stats
docker stats --no-stream --format "{{.Name}}: {{.MemUsage}}"
```

## 6. Escalation Procedure

1. RSS > 12 GB → Alert, reduce load
2. RSS > 15 GB → Auto-kill Ollama (largest consumer)
3. RSS > 18 GB → Emergency: `systemctl stop skillpool-mcp-http clawmem-mcp-http`
4. OOM kill → Check `dmesg | grep -i oom`, restart services, reduce limits
