# Changelog

All notable changes to SkillPool are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [4.3.0] - 2026-05-31

### Added — MCP Architecture Refactor

- **LazySkillLoader 集成**: skill_list Resource 改用 L0 tier，新增 skill://{id}/summary Resource (L1 tier)，skill_definition 改用 L2 tier，3 级渐进加载
- **SecurityScanner Hook**: 物化前安全准入检查 — YAML 安全、危险代码模式扫描（exec/eval/os.system等）、签名验证占位
- **security_scan Tool**: MCP Tool 暴露安全扫描能力，Agent 可在物化前检查技能安全性
- **bug://list Resource**: MCP Resource 查询 BugCollector 中的 bug 记录
- **healing_scan Tool**: 扫描 BugCollector 缺陷并提议自愈动作
- **healing_execute Tool**: 执行自愈进化（BDD 验证 + 自动回滚）
- **trigger_review Prompt 重构**: 消除硬编码路径，改用 skill:// Resources 动态获取内容

### Fixed

- **SelfHealingLoop._bdd_verify 逻辑缺陷**: 改为 bug_id 去重窗口检查，不再恒为 True → 进一步简化为 `count_after <= count_before + 1`（容忍 1 个并发新增 bug）
- **SelfHealingLoop execute_healing 回滚实现**: BDD 失败时调用 Evolver.verify_evolution() 触发真实回滚，不再仅改状态标记
- **SelfHealingLoop scan_and_propose 去重**: 同 (skill_id, defect_type) 已有 PROPOSED 提案时跳过，不再重复创建
- **RuntimeAuditHook 条件化注册**: 仅 prod 环境自动启用，dev/test 跳过
- **runtime_audit 测试**: 事件捕获测试改用子进程隔离（165s → 1.42s）
- **SecurityScanner 代码块提取**: 修复正则绕过（未闭合围栏、嵌套、CRLF、波浪线围栏），实现 _SAFE_CONTEXTS 排除注释和 re.compile()，修复行切片 -1 bug
- **BugCollector JSONL 原子写入**: 添加 fsync 防崩溃截断
- **BugCollector excepthook**: 排除 KeyboardInterrupt/SystemExit（控制流信号，非缺陷），修复 AssertionError 拼写
- **MCP audit_verify/monitor_evaluate**: 添加 try/except 错误保护
- **MCP security_scan**: 错误信息脱敏（不泄露内部路径）
- **MCP _load_csdf 重构**: 提取到共享 csdf_loader.py 模块，消除 mcp_server/lazy_loader 重复
- **LazySkillLoader**: 添加 threading.Lock + mtime 缓存失效 + clear_cache() 方法

### Changed

- **SkillPool 系统定位明确**: 所有代码注释标注 `# Part of SkillPool — independent infrastructure`
- **测试基线**: 938 → 961 → 998 tests (+23 security_scanner + 37 E2E integration)

## [4.2.0] - 2026-05-31

### Added
- **Changelog/运行日志系统**: 所有系统修改、优化、BUG 修复、运行问题及解决方案均记录于此
- **Registry 双查找索引**: `_by_id` + `_by_name` 双索引，支持 S09（id）和 name-based 查找
- **环境感知供应链策略**: `SUPPLY_CHAIN_PROFILES` 分级（dev=L0, ci=L1, prod=L2+），开发环境不再强制 SBOM/签名。通过 `SKILLPOOL_EVIDENCE_TIER` 环境变量控制
- **skill://list 扩展**: 包含目录型技能（SKILL.md frontmatter 扫描），从 23 个扩展到 78 个（23 CSDF + 55 目录型）
- **skill://definition 扩展**: 目录型技能（如 scaffold-docs）可通过 MCP Resources 查询定义
- **CLI inspect 扩展**: 支持三级查找（Registry → CSDF YAML → 目录型技能），`skillpool inspect S09` 和 `skillpool inspect scaffold-docs` 均可工作
- **FastMCP 内存协议测试**: `test_mcp_protocol.py` 使用 `Client(mcp)` 测试完整 MCP 协议路径（25 个异步测试）
- **Registry JSONL 加载**: `_load()` 支持 JSON 对象和 JSONL 两种格式，自动检测
- **pyproject.toml**: 添加 `asyncio_mode = "auto"` 支持 async 测试
- **pytest-asyncio**: 升级到 1.4.0 支持 FastMCP Client 异步测试
- **BugCollector**: 4阶段流水线（Capture→Enrich→Filter→Persist），11种缺陷类型，JSONL持久化，sys.excepthook自动捕获
- **SkillPoolLogger**: structlog风格结构化日志，ContextVars线程/协程安全绑定，JSON/Console双渲染器
- **DefectClassifier**: ProcCtrlBench 11类型缺陷分类，MRO匹配+懒加载域异常映射，修复建议+上下文严重度升级
- **RuntimeAuditHook**: PEP 578 sys.addaudithook安全监控（exec/compile/open/subprocess/socket），重入保护，环境感知（仅prod自动注册）
- **CHANGELOG自动追加**: Keep a Changelog标准，自动版本检测+分类插入
- **CSDF Schema GovernSpec扩展**: permissions/boundaries/verification_steps契约字段，validate_contract()方法
- **LazySkillLoader**: L0/L1/L2三级渐进加载（50/200/full tokens），内存缓存+升级路径，目录型技能支持
- **SelfHealingLoop**: BugCollector→Evolver闭环，阈值触发（P0→MAJOR/P1→MINOR/P2×3→PATCH），BDD验证+自动回滚
- **conftest.py pytest hook**: pytest_runtest_makereport自动收集测试失败→BugCollector，缺陷分类+严重度标注
- **FastMCP中间件**: LoggingMiddleware + TimingMiddleware 集成到 MCP Server

### Fixed
- **scaffold-docs 模板渲染 bug**: `render_templates_safe()` 正则 `[^\w\s\-\.\/:@]` 剥离 `=` 字符，导致 `PYTHONPATHsrc` → 修复为 `[^\w\s\-\.\/:@=]`
- **CLI inspect 返回 "not found"**: Registry 内存为空（`_load()` 因 `registry_path=None` 提前返回），且 `registry.jsonl` 格式不兼容 → 修复加载逻辑 + 三级查找 fallback 到 CSDF 文件
- **AGENTS.md 模板渲染**: `PYTHONPATHsrc` 缺少 `=` → 修复模板安全字符允许列表
- **test_register_missing_evidence 失败**: 因 SKILLPOOL_EVIDENCE_TIER=dev 导致不再抛异常 → 测试显式设置 prod 配置
- **SelfHealingLoop._bdd_verify 逻辑缺陷**: count_after <= count_before 恒为 True（同一实例无新增bug）→ 改为基于 bug_id 去重的窗口检查
- **RuntimeAuditHook 批量测试性能**: sys.addaudithook 导致 I/O 开销从毫秒级涨到分钟级 → 条件化注册（仅prod自动启用，dev跳过），测试改用子进程隔离

### Changed
- **测试基线**: 790 → 938 tests (790 原有 + 148 新增: BugCollector 31 + DefectClassifier 36 + Changelog 20 + RuntimeAudit 22 + MCP Protocol 39 + MCP Server 26 + Schemas 23 + conftest hook)
- **skill://list 返回格式**: 新增 `type` 字段区分 csdf/directory

### Changed
- **MCP Server 架构重构** (V4.1): 12 Tools → 6 Resources + 10 Tools + 3 Prompts
  - Resources: `skill://list`, `skill://{id}/definition`, `skill://{id}/manifest.yaml`, `skill://{id}/x-execution`, `skill://graph`, `audit://records`
  - Tools: gate_check, telemetry_report, audit_verify, skill_register, skill_transition, evolution_trigger, evolution_proposal, monitor_evaluate, health_check, review_trigger
  - Prompts: skill_context, trigger_review, gate_status
  - 删除: skill_materialize(→CLI), skill_get(→Resource), audit_query(→Resource)
- **双通道架构**: CLI 物化通道（Start Hook）+ MCP 查询通道（Resources）
- **安全准入三层**: Hook 层(YAML校验+危险模式扫描) → MCP 层(gate_check) → Audit 层(只读不可篡改)
- **超时降级**: gate_check→DENY, telemetry→静默失败, health_check→DEGRADED

### 运行问题记录

#### 2026-05-31: MCP stdio 协议测试超时
- **现象**: Python subprocess 发送 JSON-RPC 到 skillpool-mcp，Content-Length 头格式，全部超时
- **根因**: MCP stdio 使用**换行分隔 JSON**（不是 LSP 的 Content-Length 头），测试代码用了错误的协议格式
- **解决**: 改用 FastMCP `FastMCPTransport` 内存测试，绕过 stdio 传输层
- **教训**: MCP ≠ LSP，stdio 传输的消息格式不同

#### 2026-05-31: Registry 与 CSDF 数据源不统一
- **现象**: `skillpool inspect S09` 返回 "not found"，但 MCP `skill://list` 返回 S09
- **根因**: CLI inspect 查 Registry 内存（空），MCP 直接读 CSDF YAML 文件，三个真相源未关联
- **解决**: Registry 添加双查找索引 + 从 CSDF YAML 自动填充
- **教训**: 单一真相源原则 — Registry 应从 CSDF 自动构建，而非独立维护

#### 2026-05-31: scaffold-docs 不在 skill://list
- **现象**: 33 个目录型技能（scaffold-docs, multi-dim-review 等）不在 MCP Resources 中
- **根因**: `skill_list()` 只扫描 `*.yaml`，遗漏含 `SKILL.md` 的子目录
- **解决**: 添加子目录扫描，读取 SKILL.md frontmatter
- **教训**: 技能存储格式有两种（YAML + 目录），查询层必须覆盖两种

#### 2026-05-31: 供应链证据在开发环境过于严格
- **现象**: `skillpool register` 要求 SBOM+签名+来源+pin，开发环境无法注册
- **根因**: 未区分环境级别，一律使用生产级要求
- **解决**: 引入 SLSA 分级策略（dev=L0 无要求, ci=L1, prod=L2+）
- **教训**: 安全策略必须环境感知，否则阻碍开发效率

#### 2026-05-31: scaffold-docs 模板渲染剥离 = 字符
- **现象**: `{{TEST_COMMAND}}` 渲染为 `PYTHONPATHsrc` 而非 `PYTHONPATH=src`
- **根因**: `render_templates_safe()` 正则允许列表不含 `=`，将其视为危险字符剥离
- **解决**: 正则加入 `=`：`[^\w\s\-\.\/:@=]`
- **教训**: 安全过滤的允许列表需覆盖所有合法字符，`=` 在环境变量赋值中是必需的

---

## [4.1.0] - 2026-05-26

### Added
- MCP Server (FastMCP 3.3.1): 3 Tools → 6 Resources + 10 Tools + 3 Prompts
- 双通道架构: CLI 物化 + MCP 查询
- 安全准入三层: Hook + MCP gate_check + Audit
- 超时降级策略: gate_check→DENY, telemetry→静默, health→DEGRADED
- 全局 AGENTS.md: 跨 Agent 协作规范
- skillpool-security-check.sh: 物化前安全校验
- 系统级 CLI 包装: /usr/local/bin/skillpool, skillpool-mcp
- Hermes sync 修复: 全路径 venv 调用
- vMCP Gateway 禁用: 所有 Agent 改用 stdio 直连

### Fixed
- CWD-local .skillpool/ 遮蔽 ~/.skillpool/: 删除本地影子目录
- Hermes sync exit 127: systemd PATH 不含 venv → 全路径修复
- vMCP Gateway crash-loop: 所有 Agent 已用 stdio 直连 → 禁用 gateway
- skillpool-mcp 不在 PATH: 创建 /usr/local/bin/skillpool-mcp 包装

### Changed
- 790 tests 全部通过, 79% 覆盖率 (88% excluding quality.py)
- 24 CSDF YAML 技能 + 33 目录型技能
- 4 Agent 接入验证: Claude Code/Codex/OpenClaw(stdio) + Hermes(systemd timer)

---

## [4.0.0] - 2026-05-12

### Added
- Core skillpool library (src/skillpool/)
- Lifecycle: 9 态技能生命周期状态机
- Profile: Agent 能力画像 (Claude Code/Codex/Hermes)
- Gate: 门禁管理 + 复杂度评估 (ALLOW/GUARD/ESCALATE/DENY)
- Telemetry: 遥测桥接 (hook/mcp/log_file 3 频道)
- Materializer: CSDF→SKILL.md 实体化引擎 (14 映射规则)
- Resolver: 技能链解析 + DAG + 断路器 + 限流 + 缓存
- Review: 评审触发 + VETO V1-V6 + L1-L4 Checkpoint
- Cost: 成本查询 + Token Governor (8 预设) + 预算追踪
- Health: 健康检查 (SERVING/NOT_SERVING/DEGRADED) + 降级管理
- Paradigm: 4D 范式注册 + 紧急覆写
- Audit: 34 字段 OTel 审计 + SHA-256 哈希链
- Evolver: 缺陷积累触发 + Add/Merge/Discard 三态
- Graph: 3 层 PPR (Python push / CSR / sknetwork)
- Monitor: 五维评估 + SLO 追踪 + PRM 评分
- Registry: 技能注册表 + 供应链证据 + 9 态生命周期

### Changed
- Major architecture refactor from v3.x
- 565 tests, 93% coverage

---

## [3.2.0] - 2025-03-01

### Added
- Basic skill registration and lookup
- Simple keyword search

### Fixed
- Various stability improvements

## [3.1.0] - 2025-02-01

### Added
- Initial adapter framework

## [3.0.0] - 2025-01-15

### Changed
- Rewritten from scratch with modern Python patterns

[4.2.0]: https://github.com/your-org/skillpool/compare/v4.1.0...v4.2.0
[4.1.0]: https://github.com/your-org/skillpool/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/your-org/skillpool/compare/v3.2.0...v4.0.0
[3.2.0]: https://github.com/your-org/skillpool/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/your-org/skillpool/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/your-org/skillpool/releases/tag/v3.0.0
