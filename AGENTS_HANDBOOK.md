---
title: "交接手册"
version: "1.0"
generated_by: "scaffold-docs v1.0.0"
generated_at: "2026-05-30T20:09:17.76455600:00"
last_verified: "2026-05-30T20:09:17.76455600:00"
diataxis_type: "explanation"
audience: "all"
status: "active"
layout: "single"
auto_refresh: "false"
---

# 交接手册 (AGENTS_HANDBOOK)

## 双环境路径映射

| 环境 | 路径 |
|------|------|
| WSL | /root/skillpool |
| Windows | — |

<!-- MANUAL START -->
> 补充Windows侧路径（如有双环境需求）
<!-- MANUAL END -->

## 工具链版本（验证命令）

| 工具 | 验证命令 | 最低版本 |
|------|---------|---------|
| Python3 | `python3 --version` | 3.10+ |
| ripgrep | `rg --version` | 13.0+ (可选) |
| jq | `jq --version` | 1.6+ (可选) |
| git | `git --version` | 2.30+ (可选) |

## 常见陷阱

| 陷阱 | 现象 | 解决方案 |
|------|------|---------|
| BUG Collector自动触发 | 任务执行中突然生成83KB噪声文件 | 已改为opt-in: conftest需`--with-collector`，pre-commit用`stages:[manual]`，MCP需无`--skip-collector` |
| Agent误读BUG_TRACKER.md | Agent试图修复39个P2 ruff格式问题(非功能bug) | 铁律第4条=强制禁令，本条=操作指引(解释为什么)，DOC_MAP标注=分类元数据 |
| 路径含特殊字符 | 脚本中路径未加引号导致解析失败 | 路径含空格/特殊字符时用引号包裹 |
| Cron环境变量缺失 | cron任务找不到Python或项目路径 | cron脚本中显式设置PATH和PYTHONPATH |

<!-- MANUAL START -->
> 补充项目特有陷阱
<!-- MANUAL END -->

## 常用命令清单

```bash
# 测试
PYTHONPATHsrc pytest tests/ -v

# 代码地图生成
scripts/gen-code-map.sh src/ docs/

# 健康检查
scripts/health-check.sh

# 文档过时检测
scripts/check-doc-staleness.sh

# 全量文档刷新
scripts/refresh-all-docs.sh

# 链接验证
scripts/validate-links.sh
```

## 如何更新文档体系

| 文档 | 更新方式 | 自动化 |
|------|---------|--------|
| AGENTS.md | 手动编辑 | 无 |
| PROJECT_ATLAS.md | 手动编辑 | 目录树可脚本生成 |
| DOC_MAP.md | 手动编辑 | 无 |
| CODE_MAP.md | `scripts/gen-code-map.sh` | 脚本生成+人工补充 |
| TASK_MAP.md | 手动编辑 | 无 |
| AGENTS_HANDBOOK.md | 手动编辑 | 无 |
| symbol-index.json | `scripts/gen-code-map.sh` | 脚本生成 |

## Fallback 模式

当系统缺少 ripgrep(rg) 或 jq 时：

```bash
# gen-code-map.sh 自动检测 rg/jq，缺失时使用 Python fallback:
# scripts/gen_code_map_py.py --source src/ --output docs/symbol-index.json
# Python fallback 使用 ast 模块提取 Python 符号，正则提取 Go/Rust/JS/TS 符号
# 零外部依赖，项目已有 Python 3.10+ 环境

# 安装推荐（可选，提升性能）:
sudo apt install ripgrep jq
```

## 紧急恢复步骤

1. 文档损坏：从git恢复 `git checkout HEAD -- <file>`
2. 脚本失效：重新运行 `python3 scaffold-docs.skill/main.py --target . --force`
3. 健康检查失败：按错误提示安装缺失依赖
4. 符号索引过期：`scripts/gen-code-map.sh src/ docs/` 重新生成

## 提交前检查: 4D 流程 L1 评审项

- [ ] 所有文档 frontmatter 版本号已更新
- [ ] CODE_MAP.md 符号索引与源码一致
- [ ] DOC_MAP.md 无缺失/过时条目
- [ ] TASK_MAP.md 无P0阻断项
- [ ] AGENTS_HANDBOOK.md 陷阱表无新增未记录陷阱
- [ ] health-check.sh 全绿
- [ ] `skillpool review --checkpoint L1` 通过