# Implement Smart API URL Handling Spec

## Why
当前系统处理 API URL 时存在诸多不确定性。为确保系统能够稳定兼容各种供应商接口配置，需要实现一套智能的 API URL 处理机制。核心在于：规范化输入的基础 URL，以及在不同业务场景（如获取模型列表、发送聊天请求）下自动补充特定的后缀端点，并加入充足的错误处理与日志记录。

## What Changes
- **API URL 保存机制调整**：用户在输入框填写 URL 后保存时，系统会验证其格式。如果未以 `/v1` 结尾，则自动补充 `/v1`；如果已经以 `/v1` 结尾，则保持原样。
- **模型列表获取逻辑更新**：在请求可用模型列表时，系统将使用基础 URL 并自动补充 `/chat/completions` 后缀。
- **聊天功能端点更新**：聊天请求统一使用基础 URL + `/chat/completions` 作为最终请求端点。
- **强化技术要求**：
  - 新增 URL 格式验证逻辑。
  - 补充完善的错误处理与网络异常捕获机制。
  - 补充清晰的日志记录（前后端），用于追踪实际发起的 URL 请求与错误信息。

## Impact
- Affected specs: 供应商配置模块、模型列表获取模块、聊天模块。
- Affected code:
  - 前端供应商设置与 API 封装部分
  - 后端模型配置解析、模型列表获取路由
  - 后端执行层（聊天请求发起）

## ADDED Requirements
### Requirement: 智能 URL 规范化与格式验证
系统 SHALL 在保存供应商 API URL 前，验证其 URL 格式，并智能补全 `/v1` 后缀。

#### Scenario: 用户输入不带 v1 后缀的合法 URL
- **WHEN** 用户输入 `https://api.deepseek.com/` 并保存
- **THEN** 系统将其自动规范化为 `https://api.deepseek.com/v1` 并保存，同时记录日志

#### Scenario: 用户输入已带 v1 后缀的合法 URL
- **WHEN** 用户输入 `https://api.deepseek.com/v1` 并保存
- **THEN** 系统识别出已有 `/v1`，直接保存原值

### Requirement: 获取模型列表
系统 SHALL 在获取可用模型列表时，自动基于基础 URL 拼接 `/chat/completions` 后缀发起请求。

#### Scenario: 成功获取模型
- **WHEN** 用户点击获取模型列表
- **THEN** 系统请求 `<base_url>/chat/completions`，并正确解析返回结果显示在界面上

### Requirement: 发送聊天请求
系统 SHALL 在进行聊天交互时，自动基于基础 URL 拼接 `/chat/completions` 后缀。

#### Scenario: 正常聊天交互
- **WHEN** 用户发送聊天消息
- **THEN** 系统请求 `<base_url>/chat/completions`，成功响应并记录相关网络请求日志

## MODIFIED Requirements
### Requirement: 错误处理与日志追踪
修改现有网络请求与配置流程，必须覆盖网络异常、URL 格式非法等边缘情况，并通过日志明确暴露。
