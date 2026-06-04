# Gate Policy — Operations Manual

> Phase: DocsDD | Level: L2 | Date: 2026-06-04

## 1. Configuration Management

### 1.1 gate.policy Location

Default: `<project_root>/gate.policy` or `~/.skillpool/skills/dev-4d-orchestrator/gate.policy`

Override via environment variable: `GATE_POLICY_PATH=/custom/path/gate.policy`

### 1.2 gate.policy Validation

Before committing changes:
```bash
python3 -c "
from skillpool.gate_policy.parser import load_gate_policy
from pathlib import Path
config = load_gate_policy(Path('gate.policy'))
print(f'Loaded {len(config.directory_overrides)} directory overrides')
print(f'Loaded {len(config.file_patterns)} file patterns')
print(f'Default level: {config.default_level}')
"
```

### 1.3 Common Configuration Changes

**Add new directory override**:
```yaml
# In gate.policy, under directory_overrides:
- path: "src/new_module/"
  minimum_level: L2
  reason: "New module requires full 4D process"
```

**Change default complexity level**:
```yaml
# In gate.policy, top level:
default_level: L1  # Was L2
```

**Add emergency bypass window**:
```yaml
# In gate.policy, under emergency_bypass:
enabled: true
max_duration_hours: 48  # Was 24
```

## 2. State Management

### 2.1 gate.json Location

Default: `<project_root>/.gate/gate.json`

Override via environment variable: `GATE_STATE_PATH=/custom/path/gate.json`

### 2.2 State Recovery

**Scenario: Corrupt gate.json**

Symptoms:
- `GatePolicyError(GP006)` on state machine init
- gate.json contains invalid JSON

Recovery:
```bash
# Backup corrupt file
mv .gate/gate.json .gate/gate.json.corrupt

# Reset to initial state
python3 -c "
from skillpool.gate_policy.state_machine import GateStateMachine
from pathlib import Path
sm = GateStateMachine(Path('.gate/gate.json'))
print('State reset to IDLE')
"
```

**Scenario: Stuck in wrong phase**

Symptoms:
- `current_phase` shows wrong value
- Transitions blocked unexpectedly

Recovery:
```bash
# Manual state reset (use with caution)
python3 -c "
import json
from pathlib import Path
state = Path('.gate/gate.json')
data = json.loads(state.read_text())
data['current_phase'] = 'IDLE'
data['assessed_level'] = None
data['phase_history'] = []
state.write_text(json.dumps(data, indent=2))
print('State reset to IDLE')
"
```

### 2.3 State Inspection

```bash
# View current state
cat .gate/gate.json | python3 -m json.tool

# Check specific fields
python3 -c "
import json
from pathlib import Path
data = json.loads(Path('.gate/gate.json').read_text())
print(f'Phase: {data[\"current_phase\"]}')
print(f'Level: {data[\"assessed_level\"]}')
print(f'Files: {len(data[\"changed_files\"])} changed')
print(f'History: {len(data[\"phase_history\"])} transitions')
"
```

## 3. Troubleshooting

### 3.1 Error Code Reference

| Code | Message | Resolution |
|------|---------|------------|
| GP001 | gate.policy not found | Check `GATE_POLICY_PATH` env var or create gate.policy |
| GP002 | YAML parse error | Validate YAML syntax with `yamllint gate.policy` |
| GP003 | Illegal phase transition | Check current phase and allowed transitions in architecture doc |
| GP004 | Missing artifact for gate | Complete required phase artifacts before transition |
| GP005 | git diff execution failure | Ensure git is installed and current dir is a git repo |
| GP006 | gate.json read/write failure | Check file permissions, disk space, parent directory exists |

### 3.2 Common Issues

**Issue: "incremental_mode=True but no files detected"**

Cause: Not in a git repository, or `git diff` returns empty

Resolution:
```bash
# Verify git status
git status

# Check if files are staged
git diff --name-only HEAD

# If not a git repo, disable incremental mode or provide changed_files manually
```

**Issue: "Directory override not applied"**

Cause: Path in gate.policy doesn't match actual file path

Resolution:
```bash
# Check path matching
python3 -c "
from skillpool.gate_policy.parser import load_gate_policy, resolve_level_for_path
from pathlib import Path
policy = load_gate_policy(Path('gate.policy'))
result = resolve_level_for_path('src/core/myfile.py', policy)
print(f'Matched rules: {result.matched_rules}')
"
```

**Issue: "Enforcement mode not blocking illegal transitions"**

Cause: `enforcement.mode` set to `permissive` or `disabled`

Resolution:
```yaml
# In gate.policy:
enforcement:
  mode: "strict"  # Ensure this is set
```

## 4. Monitoring

### 4.1 Health Check

```bash
# Quick health check
python3 -c "
from skillpool.gate_policy.parser import load_gate_policy
from skillpool.gate_policy.state_machine import GateStateMachine
from pathlib import Path

try:
    policy = load_gate_policy(Path('gate.policy'))
    sm = GateStateMachine(Path('.gate/gate.json'))
    print('✓ Gate policy system healthy')
    print(f'  Policy version: {policy.version}')
    print(f'  Current phase: {sm.state.current_phase}')
except Exception as e:
    print(f'✗ Health check failed: {e}')
"
```

### 4.2 Metrics (for future integration)

- `gate_policy_loads_total`: Counter of policy loads
- `gate_state_transitions_total`: Counter by (from_phase, to_phase)
- `gate_check_duration_seconds`: Histogram of gate check latency
- `incremental_files_detected`: Gauge of changed files count

## 5. Security Operations

### 5.1 Access Control

- gate.policy should be read-only for most developers
- gate.json should be writable by the agent process only
- Emergency bypass requires explicit enable in gate.policy

### 5.2 Audit Trail

All phase transitions are logged to `phase_history` in gate.json:
```json
{
  "phase_history": [
    {"from": "IDLE", "to": "ASSESSING", "timestamp": "2026-06-04T10:00:00Z", "reason": "assess called"},
    {"from": "ASSESSING", "to": "SDD", "timestamp": "2026-06-04T10:00:05Z", "reason": "L1 path selected"}
  ]
}
```

### 5.3 Emergency Procedures

**Enable emergency bypass**:
```yaml
# In gate.policy:
emergency_bypass:
  enabled: true
  config_file: "emergency_overrides.json"
  max_duration_hours: 24
```

**Create emergency override**:
```json
// In emergency_overrides.json:
{
  "active": true,
  "reason": "Critical production hotfix",
  "created_at": "2026-06-04T10:00:00Z",
  "expires_at": "2026-06-05T10:00:00Z",
  "allowed_phases": ["SDD", "TDD"]
}
```

**Disable after emergency**:
```yaml
emergency_bypass:
  enabled: false
```
