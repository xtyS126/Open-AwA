# 全仓代码审查与结构化报告 Spec

## Why
当前仓库缺少一次覆盖源代码、配置、测试脚本与文档的统一质量审查，难以及时发现跨层级的一致性、稳定性与合规风险。
本次变更需要建立一套可执行的全仓审查规格，输出结构化问题报告，并将静态扫描、测试与回归验证纳入合并前门禁。

## What Changes
- 建立覆盖后端、前端、配置、CI、测试与文档的全仓代码审查范围
- 统一问题分级为致命、严重、一般、建议，并定义判定口径
- 规定每条问题必须包含文件路径、行号、问题描述、风险说明、修复建议与参考规范链接
- 将代码风格、命名规范、逻辑正确性、边界条件、性能、资源泄露、安全、依赖与许可证、测试有效性、CI 正确性、API 兼容性、日志脱敏、错误处理与回滚机制纳入审查维度
- 规定审查结论必须区分“已验证事实”“待确认风险”“未覆盖项”
- 规定所有拟合并修复项在合并前必须通过静态扫描、单元测试、集成测试与回归测试验证
- **BREAKING** 将“代码审查完成”的定义提升为“已形成结构化报告且合并门禁验证策略明确”，不再接受仅口头总结式审查

## Impact
- Affected specs: 质量审查流程、缺陷分级规则、测试与发布门禁、文档审计规范
- Affected code: 全仓库源代码文件、配置文件、测试脚本、CI 配置、依赖清单、项目文档

## ADDED Requirements
### Requirement: Full Repository Review Scope
系统 SHALL 对整个代码仓库执行一次全量代码审查，覆盖所有源代码文件、配置文件、测试脚本与文档。

#### Scenario: Review All Repository Assets
- **WHEN** 启动本次审查任务
- **THEN** 审查范围 SHALL 包含后端、前端、脚本、依赖清单、CI 配置、容器或部署配置、测试代码与项目文档

### Requirement: Structured Finding Report
系统 SHALL 输出结构化问题报告，并为每条问题提供最小可执行修复信息。

#### Scenario: Record One Finding
- **WHEN** 发现一条问题
- **THEN** 报告 SHALL 至少包含严重程度、文件路径、行号、问题描述、风险说明、修复建议与参考规范链接

### Requirement: Severity Classification
系统 SHALL 使用统一分级体系对问题进行分类，并保证分类依据可解释。

#### Scenario: Classify A Finding
- **WHEN** 评估问题影响
- **THEN** 问题 SHALL 被分类为致命、严重、一般或建议之一，并说明影响范围与触发条件

### Requirement: Multi-Dimension Review Coverage
系统 SHALL 按既定维度执行审查，避免只聚焦单一类型问题。

#### Scenario: Apply Review Dimensions
- **WHEN** 执行仓库审查
- **THEN** 审查 SHALL 覆盖代码风格与命名规范、逻辑正确性与边界条件、性能瓶颈与资源泄露、安全漏洞、依赖版本与许可证、测试覆盖率与用例有效性、CI 脚本、API 兼容性与版本管理、日志完整性与脱敏、错误处理与回滚机制

### Requirement: Evidence Traceability
系统 SHALL 让每一条审查结论可追溯到代码或配置证据。

#### Scenario: Link Finding To Evidence
- **WHEN** 输出问题报告
- **THEN** 每条问题 SHALL 能定位到对应文件与代码位置，无法精确定位时必须说明原因与证据来源

### Requirement: Merge Gate Verification Policy
系统 SHALL 明确修复项在合并前的验证门禁。

#### Scenario: Verify Before Merge
- **WHEN** 审查报告包含待修复问题
- **THEN** 合并前 SHALL 完成静态扫描、单元测试、集成测试与回归测试，并记录验证结果与未通过项

### Requirement: API Compatibility Review
系统 SHALL 对 API 接口兼容性与版本管理进行专项审查。

#### Scenario: Review API Compatibility
- **WHEN** 审查后端接口或前端调用契约
- **THEN** 系统 SHALL 检查请求格式、响应结构、字段兼容、错误码一致性、版本策略与向后兼容风险

### Requirement: Dependency And License Compliance Review
系统 SHALL 对依赖版本合规性与许可证冲突进行专项审查。

#### Scenario: Review Dependencies
- **WHEN** 审查依赖清单与锁文件
- **THEN** 系统 SHALL 检查高风险版本、过期依赖、未锁定版本、许可证冲突与供应链风险

### Requirement: Logging And Sensitive Data Review
系统 SHALL 对日志完整性和敏感信息脱敏进行专项审查。

#### Scenario: Review Logging
- **WHEN** 审查日志与异常处理链路
- **THEN** 系统 SHALL 检查关键路径是否记录日志、是否暴露凭证或个人信息、是否具备请求关联标识与错误上下文

### Requirement: Error Handling And Rollback Review
系统 SHALL 对错误处理、事务一致性与回滚机制完备性进行专项审查。

#### Scenario: Review Failure Paths
- **WHEN** 审查异常路径或失败流程
- **THEN** 系统 SHALL 检查异常捕获、错误传播、补偿逻辑、事务回滚、部分失败处理与用户可见反馈

## MODIFIED Requirements
### Requirement: Code Review Output
代码审查输出不再限于概述性总结，而是必须产出结构化、可追踪、可验证的审查报告，并标注已验证事实与待确认事项。

### Requirement: Quality Gate Completion
质量门禁完成条件修改为：关键问题得到分级、证据可追溯、修复建议可执行、验证策略完整，而不是仅完成人工浏览。

## REMOVED Requirements
### Requirement: 仅聚焦源代码文件
**Reason**: 当前需求明确要求同时覆盖配置文件、测试脚本与文档，旧范围过窄。
**Migration**: 将配置、测试、CI 与文档纳入统一审查清单，并在报告中单独分区呈现。
