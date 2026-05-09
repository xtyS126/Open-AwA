# 代码存活性审查与最佳实践规范

## Why

自上次全仓审计（2026年3月）以来，项目经历了大规模功能演进，包括：插件系统重构（plugin event bus、dependency resolver、hot-update）、AI Agent 流式工具调用链路重构、twitter-monitor 插件集成、定时任务系统、向量记忆与工作流引擎等重大变更。与此同时，之前审计报告中的 P0/P1/P2/P3 问题已全部修复。

然而，代码量的快速增长（后端 113 个 Python 文件、前端 77 个 TS/TSX 文件、42+35 个测试文件）带来了新的质量挑战：异常处理是否完备、边界条件是否覆盖、并发安全是否保障、性能是否可接受。本次审查聚焦于代码的**存活性（Robustness）**，目标是发现并归零中等以上的质量风险，输出可执行的修复计划，并建立可持续的代码质量规范。

## What Changes

- **审查范围**：覆盖后端所有 Python 源文件、前端所有 TS/TSX 源文件、配置文件、测试文件、插件代码
- **审查维度**：
  1. 异常处理与边界条件（exception handling, edge cases, null/None checks）
  2. 输入验证与数据校验（input validation, type safety, schema validation）
  3. 错误处理与日志记录（error propagation, logging adequacy, log leakage）
  4. 内存与并发安全（memory leaks, race conditions, thread safety, async safety）
  5. 代码复用与模块化（code duplication, coupling, cohesion, DRY）
  6. 性能瓶颈（N+1 queries, blocking calls, hot paths, caching）
- **产出物**：
  1. 结构化审查报告（按风险等级分类的问题清单，含文件路径、行号、风险说明、修复建议）
  2. 修复计划（分优先级、分阶段的修复任务）
  3. 代码质量检查清单（CI 门禁可引用）
  4. 最佳实践规范文档（团队开发遵循的统一标准）
- **验证**：所有修复项需通过现有测试套件验证

## Impact

- Affected specs: 代码审查流程、质量门禁规范、开发规范文档
- Affected code: 全仓库源代码文件（后端 113 个 Python 文件、前端 77 个 TS/TSX 文件、42+35 个测试文件、22+ 配置文件、5 个插件）

## ADDED Requirements

### Requirement: 异常处理完备性审查

系统 SHALL 对全部核心业务逻辑进行异常处理完备性审查。

#### Scenario: 核心 Agent 执行路径
- **WHEN** 审查 `core/agent.py`、`core/executor.py`、`core/litellm_adapter.py`
- **THEN** 系统 SHALL 检查所有 LLM 调用、工具调用、流式处理的异常捕获与降级策略，确认无未捕获异常路径

#### Scenario: WebSocket 长连接
- **WHEN** 审查 WebSocket 连接管理
- **THEN** 系统 SHALL 检查断线重连、连接泄漏、消息序列化失败、Panic 恢复等场景

#### Scenario: 插件执行沙箱
- **WHEN** 审查插件加载、执行、热更新链路
- **THEN** 系统 SHALL 检查插件崩溃隔离、超时控制、资源释放

### Requirement: 输入验证完整性审查

系统 SHALL 对所有外部输入点进行验证完整性审查。

#### Scenario: API 输入验证
- **WHEN** 审查所有 API 路由（18 个路由文件）
- **THEN** 系统 SHALL 检查 Pydantic schema 定义、路径参数校验、查询参数校验、请求体校验是否完整

#### Scenario: 文件上传
- **WHEN** 审查文件上传接口
- **THEN** 系统 SHALL 检查文件类型白名单、大小限制、路径穿越防护

#### Scenario: 插件配置
- **WHEN** 审查插件配置加载
- **THEN** 系统 SHALL 检查 schema.json 校验、默认值处理、类型转换安全

### Requirement: 错误处理与日志审计

系统 SHALL 对错误传播和日志记录进行充分性审查。

#### Scenario: 关键路径错误传播
- **WHEN** 审查 Agent 执行、计费扣减、记忆持久化等关键路径
- **THEN** 系统 SHALL 确认错误被正确传播到上层、用户收到有意义的反馈、无静默吞异常

#### Scenario: 日志记录完整性
- **WHEN** 审查日志记录点
- **THEN** 系统 SHALL 确认关键事件有日志、错误有堆栈、日志包含请求 ID 用于关联、无敏感信息泄露

### Requirement: 并发与内存安全审查

系统 SHALL 对并发访问和资源管理进行安全审查。

#### Scenario: 共享状态并发
- **WHEN** 审查全局变量、缓存、连接池
- **THEN** 系统 SHALL 检查是否有线程不安全的数据结构、缺少锁保护、连接泄漏

#### Scenario: 异步协程安全
- **WHEN** 审查 `async/await` 链
- **THEN** 系统 SHALL 检查是否有阻塞调用混入事件循环、Task 泄漏、回调异常未捕获

### Requirement: 代码复用性评估

系统 SHALL 对代码模块化和复用程度进行评估。

#### Scenario: 重复代码检测
- **WHEN** 审查同层模块
- **THEN** 系统 SHALL 标注明显的重复实现、可提取公共函数/基类的代码段

#### Scenario: 模块耦合度
- **WHEN** 审查模块间引用关系
- **THEN** 系统 SHALL 评估循环依赖、上帝类、过长的函数/文件

### Requirement: 性能瓶颈识别

系统 SHALL 对潜在性能瓶颈进行审查。

#### Scenario: 数据库访问
- **WHEN** 审查 ORM 查询
- **THEN** 系统 SHALL 检查是否存在 N+1 查询、缺少索引的查询、未分页的查询

#### Scenario: LLM 调用
- **WHEN** 审查 LLM 调用链
- **THEN** 系统 SHALL 检查超时配置、重试策略、流式 buffer 大小、并发限制

### Requirement: 审查报告格式

审查报告 SHALL 使用统一的结构化格式。

#### Scenario: 报告问题条目
- **WHEN** 记录一条问题
- **THEN** 报告 SHALL 包含：问题 ID、严重等级（致命/严重/一般/建议）、文件路径、行号、问题描述、风险说明、修复建议

#### Scenario: 报告汇总
- **WHEN** 输出最终报告
- **THEN** 报告 SHALL 包含问题汇总统计、按等级分布、按模块分布、Top 风险项

### Requirement: 修复计划规范

修复计划 SHALL 包含明确的优先级和依赖关系。

#### Scenario: 修复任务定义
- **WHEN** 定义修复任务
- **THEN** 任务 SHALL 包含：任务描述、涉及文件、预估工作量、前置依赖

### Requirement: 最佳实践规范

系统 SHALL 建立项目级的代码最佳实践规范。

#### Scenario: 规范内容
- **WHEN** 定义开发规范
- **THEN** 规范 SHALL 覆盖：异常处理模式、输入校验标准、日志记录标准、并发安全准则、命名规范、测试标准

## MODIFIED Requirements

无修改的需求。

## REMOVED Requirements

无移除的需求。
