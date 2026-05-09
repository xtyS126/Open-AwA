# 微信扫码绑定失败溯源与修复 Spec

## Why
当前项目已完成微信二维码登录与轮询对齐，但仍存在“用户扫码后绑定失败”的问题。需要基于 `d:\代码\Open-AwA\插件\openclaw-weixin` 完整源码做一次从扫码回调、OAuth 授权、用户绑定到错误处理的端到端排查，定位具体失效点并形成可执行修复方案。

## What Changes
- 深入梳理 openclaw-weixin 源码中与扫码绑定、授权换票、身份关联、回调校验相关的核心模块与调用链
- 对比当前项目实现与源码真实流程，定位导致绑定失败的具体代码位置、状态机断点、参数丢失或校验错误
- 设计并实施后端与前端的修复，使扫码后绑定流程可正确完成并具备可观测性
- 补齐围绕绑定流程的测试、日志验证与异常路径校验
- 输出完整的绑定流程分析报告，明确问题根因、修复点、验证结果与后续风险

## Impact
- Affected specs: 微信二维码登录、微信身份绑定、通讯页登录闭环、weixin 适配器调用链
- Affected code: `插件/openclaw-weixin/源码/openclaw-weixin/src/auth/*`、`插件/openclaw-weixin/源码/openclaw-weixin/src/api/*`、`插件/openclaw-weixin/源码/openclaw-weixin/src/monitor/*`、`backend/api/routes/skills.py`、`backend/skills/weixin_skill_adapter.py`、相关前端通讯页与测试文件

## ADDED Requirements
### Requirement: 提供完整扫码绑定链路分析
系统 SHALL 基于 openclaw-weixin 完整源码输出从扫码、授权、回调、绑定到落库/配置回填的端到端流程分析，并标记每个关键节点的输入、输出、状态与失败条件。

#### Scenario: 识别核心模块
- **WHEN** 开始分析微信扫码绑定失败问题
- **THEN** 必须明确源码中处理扫码回调、OAuth 参数、绑定状态推进、用户关联与错误记录的核心代码模块

#### Scenario: 输出失败根因
- **WHEN** 完成源码与当前项目实现对比
- **THEN** 必须指出导致绑定失败的具体代码位置、触发条件、错误表现与影响范围

### Requirement: 验证 OAuth 与绑定机制
系统 SHALL 校验扫码后的 OAuth 授权与用户绑定逻辑，覆盖 code 获取、access_token 换取、openid 提取、state 校验及本地用户关联机制。

#### Scenario: OAuth 关键步骤可追踪
- **WHEN** 分析扫码回调流程
- **THEN** 必须能追踪 code、access_token、openid、state 等关键参数在源码与当前项目中的传递路径

#### Scenario: 用户身份可正确关联
- **WHEN** 用户完成扫码并返回系统
- **THEN** 系统必须能根据 openid 或等价身份标识正确关联到本地用户账号，且绑定结果可被后续流程读取

### Requirement: 修复扫码绑定失败问题
系统 SHALL 修复已确认的绑定失败根因，并保证扫码后绑定流程在成功路径和关键异常路径下都具备明确反馈。

#### Scenario: 绑定成功
- **WHEN** 用户扫码并完成授权确认
- **THEN** 绑定流程应成功推进，必要账号信息或绑定状态应被正确保存并反馈到调用方

#### Scenario: 状态或参数异常
- **WHEN** 回调 URL、state、code、token 或 openid 缺失、失效或不匹配
- **THEN** 系统必须返回明确错误，并记录足够日志帮助定位原因

### Requirement: 提供绑定失败分析报告
系统 SHALL 在实现修复后提供完整分析报告，覆盖真实流程、问题根因、修复方案、验证结果与剩余风险。

#### Scenario: 交付分析报告
- **WHEN** 完成排查与修复
- **THEN** 必须形成一份可供研发排障的绑定流程分析报告，包含源码模块映射、失败代码位置、修复说明与验证结论

## MODIFIED Requirements
### Requirement: 微信登录闭环验证
现有微信二维码登录闭环 requirement 扩展为：不仅要完成二维码展示、轮询与登录成功回填，还必须验证扫码后的身份绑定与授权确认链路完整可用，且不能在“已扫码”到“已绑定”之间静默失败。

## REMOVED Requirements
### Requirement: 无
**Reason**: 本次工作以补齐分析与修复为主，不移除既有能力。
**Migration**: 不涉及。
