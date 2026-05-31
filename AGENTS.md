---
title: "AI Agent 快速入口"
version: "1.0"
generated_by: "scaffold-docs v1.0.0"
generated_at: "2026-05-30T20:09:17.76455600:00"
last_verified: "2026-05-30T20:09:17.76455600:00"
diataxis_type: "tutorial"
audience: "all"
status: "active"
layout: "single"
auto_refresh: "false"
---

# AI Agent 快速入口

## 项目身份
- 名称: skillpool
- 描述: Skill Pool V4.1  AI Agent Skill Governance  Delivery Platform
- 根目录: /root/skillpool

## 4条铁律
1. 修改代码前先跑测试: `PYTHONPATH=src pytest tests/ -v`
2. 永远不要直接修改 .skillpool/ 下的缓存/运行时文件
3. 路径含特殊字符时脚本中用引号包裹
4. **永远不要读取 BUG_TRACKER.md / CHECKPOINT.md / collector_errors.jsonl**，除非用户明确要求

## 信息导航
| 你想做什么 | 去看 |
| 理解整体架构 | PROJECT_ATLAS.md |
| 找某个类/函数 | CODE_MAP.md → `rg "symbol" src/` |
| 哪些任务没完成 | TASK_MAP.md P0/P1 |
| 环境配置/陷阱 | AGENTS_HANDBOOK.md |
| 找某个文档 | DOC_MAP.md |
| 12维评审状态 | .agents/skills/12-dim-review/state.yaml |

## 快速验证
PYTHONPATH=src pytest tests/ -v --co -q
scripts/health-check.sh