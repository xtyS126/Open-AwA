# 修复模型选择器失效问题 Spec

## Why
聊天页面的模型选择器显示"暂无可用模型"，导致用户无法切换AI模型。根本原因是数据库中`model_configurations`表为空，而系统只初始化了`model_pricing`表的数据。

## What Changes
- **后端**：在应用启动时自动初始化默认的ModelConfiguration数据
- **前端**：增强错误处理和用户体验
- **数据完整性**：确保ModelConfiguration和ModelPricing数据一致

## Impact
- Affected specs: 聊天功能、计费系统
- Affected code:
  - `backend/billing/pricing_manager.py` - 添加初始化方法
  - `backend/main.py` - 调用初始化方法
  - `frontend/src/pages/ChatPage.tsx` - 增强错误处理
  - `frontend/src/pages/ChatPage.css` - 样式优化

## ADDED Requirements

### Requirement: 默认模型配置初始化
当`model_configurations`表为空时，系统应自动创建默认配置。

#### Scenario: 首次启动应用
- **WHEN** 用户首次启动应用且数据库为空
- **THEN** 系统应自动创建至少3-5个常用模型的配置（OpenAI GPT-4、Claude、Gemini等）
- **AND** 第一个模型应设为默认模型

#### Scenario: 应用重启
- **WHEN** 用户重启应用
- **THEN** 已存在的配置应保持不变
- **AND** 不应重复创建相同provider:model的记录

### Requirement: 模型选择器错误处理
前端应优雅处理API错误和空数据情况。

#### Scenario: API请求失败
- **WHEN** 获取模型配置API返回错误
- **THEN** 应显示友好的错误提示"加载模型失败"
- **AND** 提供重试按钮或自动重试机制
- **AND** 记录错误日志

#### Scenario: 网络断开
- **WHEN** 用户网络断开
- **THEN** 选择器应显示"网络连接失败"
- **AND** 在网络恢复后自动重新加载

### Requirement: 模型选择持久化
用户选择的模型应保存并在下次访问时恢复。

#### Scenario: 用户切换模型
- **WHEN** 用户从下拉框选择不同模型
- **THEN** 应立即保存到localStorage
- **AND** 页面刷新后应保持上次选择
- **AND** 应高亮显示当前选中的模型

### Requirement: 模型保存功能
用户应能保存当前选择的模型为永久设置。

#### Scenario: 保存模型配置
- **WHEN** 用户点击"保存模型"按钮
- **THEN** 应向后端发送请求保存配置
- **AND** 显示成功/失败提示
- **AND** 成功后自动刷新模型列表

## MODIFIED Requirements

### Requirement: ChatPage组件初始化
**Original**: 组件在加载时从API获取配置，如果API失败则静默失败
**Modified**: 组件应包含完善的加载状态、错误处理和重试机制

## REMOVED Requirements

无

## Technical Details

### Database Schema
```sql
-- model_configurations 表
id: INTEGER PRIMARY KEY
provider: STRING (e.g., "openai", "anthropic")
model: STRING (e.g., "gpt-4", "claude-3.5-sonnet")
display_name: STRING (optional, shown in UI)
description: TEXT (optional)
api_key: TEXT (optional, per-config override)
api_endpoint: STRING (optional, for custom endpoints)
is_active: BOOLEAN (default true)
is_default: BOOLEAN (default false)
sort_order: INTEGER (default 0)
created_at: DATETIME
updated_at: DATETIME
```

### API Endpoint
```
GET /billing/configurations
Response: {
  "configurations": [
    {
      "id": 1,
      "provider": "openai",
      "model": "gpt-4",
      "display_name": "GPT-4",
      "description": "...",
      "is_active": true,
      "is_default": true,
      "sort_order": 0
    }
  ]
}
```

### Default Configurations to Create
1. OpenAI - gpt-4 (default)
2. OpenAI - gpt-4o-mini
3. Anthropic - claude-3.5-sonnet
4. Google - gemini-2.0-flash
5. DeepSeek - deepseek-chat
