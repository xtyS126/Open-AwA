# 最新日志报错修复 Spec

## Why
最新错误日志显示当前项目存在两类新的运行时问题：一类是 `AIAgent` 在缺少数据库会话时获取可用技能列表报出 `'NoneType' object has no attribute 'query'`；另一类是插件扫描阶段导入示例插件时出现 `No module named 'backend'`。这两类错误会污染日志、降低可观测性，并可能让技能/插件发现结果与真实运行状态不一致。

## What Changes
- 修复 `AIAgent` 在无数据库会话场景下获取技能列表的空引用问题，确保返回稳定结果并输出可解释日志。
- 修复插件扫描阶段对示例插件的导入环境处理，避免因为扫描时导入路径不完整而持续产生 `No module named 'backend'` 错误。
- 区分“预期可恢复异常”和“真实缺陷日志”，避免测试或扫描副作用把错误日志污染为误报。
- 增加针对最新日志问题的自动化测试与回归验证，确保日志中的对应报错不再出现或降级为结构化可解释状态。

## Impact
- Affected specs: 日志系统、插件系统、技能发现
- Affected code: `backend/core/agent.py`、`backend/plugins/plugin_manager.py`、相关测试文件、必要时日志验证文档

## ADDED Requirements
### Requirement: 无数据库会话时技能列表读取必须安全降级
系统 SHALL 在 `AIAgent` 未注入数据库会话或运行环境缺少数据库上下文时，安全返回可用技能列表结果或空列表，而不是触发空引用异常。

#### Scenario: 无数据库会话读取技能列表
- **WHEN** `AIAgent` 在 `db_session is None` 的情况下执行获取可用技能列表逻辑
- **THEN** 系统不得抛出 `'NoneType' object has no attribute 'query'`
- **THEN** 系统返回稳定、可消费的结果
- **THEN** 如确有能力受限，应输出结构化且可解释的日志，而不是未分层的异常噪声

### Requirement: 插件扫描不得因导入路径缺失产生误报错误
系统 SHALL 在扫描插件文件以提取元数据时，正确处理插件导入所需的模块搜索路径，或对不可扫描插件进行结构化降级，而不是持续输出 `No module named 'backend'` 类误报错误。

#### Scenario: 扫描引用项目模块的示例插件
- **WHEN** 插件扫描器读取依赖项目内部模块的插件文件
- **THEN** 系统应补齐扫描期导入上下文，或以受控方式跳过并记录结构化结果
- **THEN** 错误日志中不得重复出现 `Error scanning plugin file ... No module named 'backend'`

### Requirement: 最新日志报错必须具备可验证回归
系统 SHALL 为本轮最新日志问题补充测试与回归步骤，保证修复结果可以被自动化验证并与日志现象一一对应。

#### Scenario: 回归验证最新日志问题
- **WHEN** 执行针对技能列表获取与插件扫描的回归测试
- **THEN** 测试能够覆盖无数据库会话场景、插件扫描场景和对应日志行为
- **THEN** 今日错误日志中的对应报错不再复现，或被降级为结构化且可解释的预期结果

## MODIFIED Requirements
### Requirement: 错误日志质量
系统当前的日志质量要求 SHALL 从“记录异常即可”提升为“区分预期可恢复问题与真实缺陷，并避免由扫描/测试副作用产生误导性 ERROR 日志”。

## REMOVED Requirements
### Requirement: 扫描阶段直接执行任意插件导入并把失败统一记为 ERROR
**Reason**: 该策略会把导入环境差异、示例插件依赖和扫描副作用混杂成真实错误，降低日志信噪比。
**Migration**: 扫描阶段应优先补齐必要上下文；若仍不可导入，则输出结构化且分级合理的结果，并补充测试验证。
