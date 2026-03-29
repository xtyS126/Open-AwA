# 微信 Clawbot 通讯页面接入规范

## Why
当前项目已具备后端 weixin skill 适配能力，但网页端“通讯/聊天应用配置”场景尚无可视化接入入口。需要在前端通讯相关页面补齐微信 Clawbot 配置与联调能力，降低接入门槛并减少手工配置错误。

## What Changes
- 在网页通讯相关页面新增“微信 Clawbot”配置入口与引导信息。
- 增加微信 Clawbot 配置表单与字段校验，覆盖账号标识、令牌、基础地址与超时参数。
- 增加连通性检测与配置保存反馈，支持健康检查结果可视化。
- 在现有聊天应用配置流程中接入微信通道开关与状态展示。
- 明确前后端接口契约，复用现有 weixin skill 适配执行能力。

## Impact
- Affected specs: 前端通讯配置、技能配置管理、联调与可观测性
- Affected code: `frontend/src/pages/SettingsPage.tsx`、`frontend/src/pages/ChatPage.tsx`、`frontend/src/services/*`、`backend/api/routes/skills.py`、`backend/skills/weixin_skill_adapter.py`

## ADDED Requirements
### Requirement: 通讯页面微信 Clawbot 配置能力
系统 SHALL 在网页通讯相关页面提供微信 Clawbot 的可视化配置能力。

#### Scenario: 用户配置微信 Clawbot
- **WHEN** 用户在通讯配置页面填写并提交微信 Clawbot 配置
- **THEN** 系统保存配置并展示保存成功状态

#### Scenario: 配置字段缺失
- **WHEN** 用户提交缺少必填字段的配置
- **THEN** 页面阻止提交并提示具体缺失字段

### Requirement: 配置联调与健康检查
系统 SHALL 提供微信 Clawbot 的健康检查入口，并以统一结构展示结果。

#### Scenario: 健康检查成功
- **WHEN** 用户触发连接测试且后端返回成功
- **THEN** 页面展示可连接状态与关键诊断信息

#### Scenario: 健康检查失败
- **WHEN** 用户触发连接测试且后端返回失败
- **THEN** 页面展示结构化错误、修复建议和重试入口

## MODIFIED Requirements
### Requirement: 聊天应用配置页面扩展性
现有聊天应用配置页面 SHALL 支持新增微信 Clawbot 通道配置模块，且不影响已有 AI 模型配置和其他应用配置流程。

## REMOVED Requirements
### Requirement: 无
**Reason**: 本次为功能扩展，不移除现有能力。
**Migration**: 现有配置无需迁移；新增微信配置项按默认关闭策略接入。
