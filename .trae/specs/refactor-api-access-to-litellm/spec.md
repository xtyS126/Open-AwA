# API 访问统一迁移 LiteLLM Spec

## Why
当前项目存在多处直连不同供应商 API 的访问逻辑，配置与错误处理分散，导致维护成本高、兼容行为不一致。用户要求统一重构为 LiteLLM，并补齐“当前未安装 LiteLLM 包”的落地路径。

## What Changes
- 统一后端所有 LLM API 访问入口，改为通过 LiteLLM 进行请求与响应处理。
- 抽离并规范 Provider 配置到统一适配层，避免业务代码直接拼接供应商端点。
- 统一超时、重试、错误码映射、日志字段与请求追踪（request_id）行为。
- 增加 LiteLLM 依赖安装与启动前检查流程，明确未安装时的可观测报错与引导信息。
- 调整相关测试，覆盖聊天、模型列表、自动回复等核心链路在 LiteLLM 下的行为。
- **BREAKING**：移除现有“直连供应商 API 请求构造”默认执行路径，改为 LiteLLM 单一路径。

## Impact
- Affected specs: 模型调用网关、Provider 配置管理、微信自动回复调用链、聊天执行链、日志与错误处理规范
- Affected code: `backend/core/model_service.py`、`backend/core/executor.py`、`backend/api/routes/*` 中调用模型服务的接口、`backend/requirements*.txt`、相关测试目录

## ADDED Requirements
### Requirement: LiteLLM 统一调用层
系统 SHALL 提供统一的 LiteLLM 调用层，所有 LLM 请求必须经由该层发起。

#### Scenario: 聊天请求成功
- **WHEN** 用户在聊天或自动回复场景触发模型调用
- **THEN** 系统通过 LiteLLM 发起请求并返回统一格式结果

#### Scenario: LiteLLM 未安装
- **WHEN** 服务启动或首次调用时检测到 LiteLLM 依赖缺失
- **THEN** 系统返回明确错误信息并提示安装步骤，不得静默失败

### Requirement: 统一错误与观测
系统 SHALL 将 LiteLLM 层异常映射为统一业务错误结构，并记录标准化日志字段。

#### Scenario: 上游供应商返回 4xx/5xx
- **WHEN** LiteLLM 接收到供应商错误响应
- **THEN** 系统返回统一错误码、保留 request_id，并输出可检索日志

## MODIFIED Requirements
### Requirement: Provider 访问策略
系统现有“按 Provider 分支拼接 URL 并直接发起 HTTP 请求”的实现 SHALL 修改为“统一委托 LiteLLM 执行请求”，业务层仅传入模型、消息、参数与上下文。

## REMOVED Requirements
### Requirement: 直连供应商请求构造默认路径
**Reason**: 该路径与 LiteLLM 统一治理目标冲突，造成重复实现与行为漂移。  
**Migration**: 保留短期兼容开关仅用于灰度回滚；默认关闭并在验证通过后移除。
