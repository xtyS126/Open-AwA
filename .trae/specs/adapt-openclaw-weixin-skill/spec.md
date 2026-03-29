# openclaw-weixin 适配 Skill 规范

## Why
当前 `openclaw-weixin` 插件基于 `openclaw/plugin-sdk` 的 Node 插件协议实现，无法被本项目后端 Skill 引擎直接加载与执行。需要提供兼容层，把该插件能力以 Skill 形态接入现有工作流。

## What Changes
- 新增 weixin 适配层：将插件能力封装为可由 Skill 引擎调用的执行入口。
- 新增配置映射：把项目 Skill 配置转换为 weixin 插件所需运行配置。
- 新增调用协议：统一 Skill 输入输出结构，覆盖消息收发与错误返回。
- 新增健康检查与启动校验：确保适配层在缺失依赖、配置错误时可快速失败并返回可诊断信息。
- 新增最小化迁移路径：保留原插件目录结构，增加本项目侧适配代码与接入配置。

## Impact
- Affected specs: 技能执行、插件集成、运行时配置管理、错误处理
- Affected code: `backend/skills/*`、`backend/core/agent.py`、`backend/api/routes/skills.py`、`插件/openclaw-weixin/*`

## ADDED Requirements
### Requirement: Weixin 插件 Skill 适配执行
系统 SHALL 提供一个 Skill 适配器，使 `openclaw-weixin` 能以 Skill 方式被触发并返回标准结果。

#### Scenario: Skill 调用成功
- **WHEN** 用户或 Agent 调用 weixin 适配 Skill 且配置完整
- **THEN** 适配器按统一输入协议执行插件能力并返回标准化结果对象

#### Scenario: 运行依赖缺失
- **WHEN** 适配 Skill 启动时发现运行依赖缺失或版本不满足
- **THEN** 返回结构化错误信息，包含缺失项与修复建议，不触发未捕获异常

### Requirement: 配置与协议映射
系统 SHALL 将本项目 Skill 配置字段映射为 `openclaw-weixin` 所需配置，并校验必填项。

#### Scenario: 配置映射成功
- **WHEN** Skill 配置包含必要凭据与通道参数
- **THEN** 适配层生成可执行配置并通过预校验

#### Scenario: 配置不完整
- **WHEN** 缺少必填配置字段
- **THEN** 在执行前返回可读错误并指出缺失字段

## MODIFIED Requirements
### Requirement: Skill 引擎外部能力接入
Skill 引擎 SHALL 支持通过适配器接入非原生 Skill 实现，并保持与现有 Skill 结果结构一致。

## REMOVED Requirements
### Requirement: 无
**Reason**: 本次为兼容增强，不移除现有能力。
**Migration**: 无需迁移现有 Skill；仅新增 weixin 适配接入路径。
