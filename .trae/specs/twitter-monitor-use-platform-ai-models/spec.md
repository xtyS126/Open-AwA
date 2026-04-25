# Twitter Monitor 插件使用平台已配置 AI 模型

## Why

当前 twitter-monitor 插件需要用户在插件配置中手动填入 `ai_api_key`、`ai_base_url`、`ai_model` 三个字段才能使用后台自动 AI 总结功能，导致用户需要在多个地方重复配置相同的 AI 凭据，且无法复用平台已在"模型提供商管理"（`/api/billing/configurations`）中配置好的 AI 模型。

## What Changes

1. **BasePlugin** — 添加 `context` 属性（`Optional[PluginContext]`）和 `set_context()` 方法
2. **PluginManager** — 接受 `db_session_factory` 参数；插件加载时构建 PluginContext 并注入到插件实例
3. **TwitterMonitorPlugin** — 将 `ai_api_key` / `ai_base_url` / `ai_model` 三个配置字段替换为单个 `ai_model_config_id`（integer），运行时通过 PricingManager 解析为实际凭据
4. **schema.json / config.json** — 反映新的模型选择字段
5. **前端 PluginConfigPage** — 新增 `x-component: "model-selector"` 支持，渲染为动态下拉框，从 `/api/billing/configurations` 获取平台已配置的 AI 模型列表

## Impact

- Affected specs: 插件配置 UI、插件数据库访问能力、Twitter 监控自动总结链路
- Affected code:
  - `backend/plugins/base_plugin.py` — 添加 context 基础设施
  - `backend/plugins/plugin_manager.py` — 注入 db_session_factory 和 PluginContext
  - `plugins/twitter-monitor/src/index.py` — 替换 AI 凭据字段，使用 PricingManager 解析
  - `plugins/twitter-monitor/schema.json` — 更新配置表单定义
  - `plugins/twitter-monitor/config.json` — 更新默认配置
  - `frontend/src/features/plugins/PluginConfigPage.tsx` — 添加 model-selector 组件
  - `frontend/src/features/plugins/PluginConfigPage.module.css` — model-selector 样式
- No breaking changes: 向后兼容，未配置 `ai_model_config_id` 时自动总结返回提示信息

## ADDED Requirements

### Requirement: 插件数据库访问能力
The system SHALL allow plugins to access the database through `PluginContext` injected by the plugin manager.

#### Scenario: 插件通过 PricingManager 解析模型配置
- **GIVEN** 插件已通过 PluginContext 获得数据库会话工厂
- **WHEN** 插件需要调用外部 AI 进行总结
- **THEN** 插件应使用 PricingManager 根据 `ai_model_config_id` 查询 `model_configurations` 表，获取 `api_key`、`api_endpoint`、`model` 字段用于 API 调用

### Requirement: 模型配置选择 UI
The system SHALL provide a dynamic dropdown in the plugin config page allowing users to select from platform-configured AI models.

#### Scenario: 用户选择 AI 模型
- **GIVEN** 用户打开插件配置页面
- **WHEN** 页面加载 ai_model_config_id 字段
- **THEN** 应显示一个下拉框，选项为所有 `is_active == True` 的 ModelConfiguration（显示格式：`display_name (provider/model)`）
- **AND** 选项的值应为 `config_id`（integer）

## MODIFIED Requirements

### Requirement: 自动 AI 总结凭据解析
**修改前**: 插件从 config 中读取 `ai_api_key`、`ai_base_url`、`ai_model` 三个字符串字段直接用于 API 调用。

**修改后**: 插件从 config 读取 `ai_model_config_id`（integer），通过 PricingManager 从数据库解析出对应的 `api_key`、`api_endpoint`、`model`，再用于 API 调用。若未配置 `ai_model_config_id`，自动总结返回"未选择 AI 模型配置"提示。

## REMOVED Requirements

### Requirement: 手动 AI 凭据配置
**Reason**: 用户不再需要手动输入 AI API 密钥和端点，直接从平台已配置的模型中选择即可。
**Migration**: 已有配置中的 `ai_api_key` / `ai_base_url` / `ai_model` 将被忽略。用户需在插件设置中选择一个已配置的 AI 模型。
