# SkillPool Deployment Guide

## systemd (Single Node, Recommended for WSL2)

### MCP Server

```bash
# User-level service (shared state across agents)
cat > ~/.config/systemd/user/skillpool-mcp-http.service << 'EOF'
[Unit]
Description=SkillPool MCP Server (HTTP Mode)
After=network.target

[Service]
Type=simple
ExecStart=/path/to/python /path/to/skillpool-mcp --transport streamable-http --port 8101 --host 127.0.0.1
EnvironmentFile=/path/to/secrets.env
Environment=SKILLPOOL_REGISTRY_PATH=/root/.skillpool/registry.db
Restart=on-failure
RestartSec=5
MemoryHigh=256M
MemoryMax=512M
OOMScoreAdjust=-500

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now skillpool-mcp-http
```

### Metrics Server

```bash
# System-level service
cat > /etc/systemd/system/skillpool-metrics.service << 'EOF'
[Unit]
Description=SkillPool Prometheus Metrics Server
After=skillpool-mcp-http.service

[Service]
Type=simple
ExecStart=/path/to/python /path/to/metrics_server.py --port 9101
Restart=on-failure
MemoryHigh=64M
MemoryMax=128M

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now skillpool-metrics
```

### Secrets

```bash
cat > /root/.secrets/skillpool.env << 'EOF'
SKILLPOOL_API_KEY=<generated-key>
EOF
chmod 600 /root/.secrets/skillpool.env
```

## Docker Compose

```bash
docker compose -f deploy/docker-compose.yml up -d
```

The compose file includes:
- `skillpool`: MCP server on port 8101
- `skillpool-metrics`: Prometheus metrics on port 9101

## Kubernetes

```bash
kubectl apply -f deploy/k8s/
```

Includes:
- Deployment (2 replicas, RollingUpdate)
- Service (ClusterIP :8000)
- Ingress (skillpool.local)
- PVC (1Gi data volume)
- PodDisruptionBudget (minAvailable: 1)

## SQLite Migration

```bash
# Migrate from legacy JSONL/JSON to SQLite
python scripts/migrate_registry_to_sqlite.py

# Verify
sqlite3 ~/.skillpool/registry.db "SELECT COUNT(*) FROM skills"
```

## Prometheus Integration

1. Add scrape config to `prometheus.yml`:
   ```yaml
   scrape_configs:
     - job_name: skillpool
       static_configs:
         - targets: ['localhost:9101']
       scrape_interval: 15s
   ```

2. Load alert rules:
   ```bash
   promtool check rules deploy/prometheus/alert_rules.yml
   ```

3. Key alerts:
   - `SkillPoolHighErrorRate`: error rate > 5% over 5m
   - `SkillPoolHighMemory`: RSS > 256MB over 10m
   - `SkillPoolServiceDown`: metrics endpoint unreachable for 2m

## Authentication

API key authentication is enabled by setting `SKILLPOOL_API_KEY`:
- **Disabled** (default): Key not set, all requests accepted
- **Enabled**: Clients must send `Authorization: Bearer <key>` header

Agent MCP config example:
```json
{
  "skillpool": {
    "url": "http://127.0.0.1:8101/mcp",
    "headers": {"Authorization": "Bearer <key>"}
  }
}
```
