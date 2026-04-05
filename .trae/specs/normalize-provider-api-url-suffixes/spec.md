# 规范化供应商 API URL 后缀 Spec

## Why
当前供应商配置面板在保存 API URL 时会无条件补充 `v1/chat/completions`，导致用户输入已经接近目标地址时仍被重复拼接，行为不稳定。同时获取模型列表与聊天请求对 URL 后缀的处理不统一，容易因为地址末尾是否包含 `/v1` 或完整接口路径而请求失败。

## What Changes
- 调整供应商配置保存逻辑：当用户填写的 API URL 以 `/v1` 结尾时，不再追加任何内容。
- 当用户填写的 API URL 不包含 `/v1` 后缀时，保存阶段自动补充 `/v1`，例如 `https://api.deepseek.com/` 规范化为 `https://api.deepseek.com/v1`。
- 获取模型列表时，在已保存的基础 URL 上自动补充模型列表请求所需的其余后缀，再发起请求并展示返回的模型列表。
- 聊天请求时，在已保存的基础 URL 上自动补充聊天接口所需的其余后缀，避免依赖用户手工填写完整的 `/chat/completions`。
- 统一前端与后端（如存在中转层）的 URL 规范化策略，避免同一个供应商在不同功能中拼接规则不一致。

## Impact
- Affected specs: 供应商配置、模型列表拉取、聊天请求 URL 组装。
- Affected code:
  - `frontend/src/features/settings/SettingsPage.tsx`
  - 供应商配置相关的前端 API 调用封装
  - 模型列表获取逻辑
  - 聊天请求发起逻辑
  - 如有后端代理层，则涉及对应的 URL 拼接与兼容处理代码

## ADDED Requirements
### Requirement: 保存时规范化供应商基础 API URL
系统 SHALL 在保存供应商配置时将用户输入的 API URL 规范化为“基础 API 地址”，而不是强制保存完整聊天接口路径。

#### Scenario: 输入地址已以 /v1 结尾
- **WHEN** 用户在供应商详情面板中输入 `https://api.deepseek.com/v1` 并保存
- **THEN** 系统直接保存该地址，不再追加 `/chat/completions` 或其他后缀

#### Scenario: 输入地址不带 /v1 后缀
- **WHEN** 用户在供应商详情面板中输入 `https://api.deepseek.com/` 并保存
- **THEN** 系统自动将其规范化为 `https://api.deepseek.com/v1`

#### Scenario: 输入地址已经是完整聊天接口
- **WHEN** 用户输入 `https://api.deepseek.com/v1/chat/completions`
- **THEN** 系统应能兼容处理，避免再次重复拼接，并在内部转换为统一可复用的基础地址或等价规范形式

### Requirement: 获取模型列表时自动补充模型接口后缀
系统 SHALL 基于已保存的基础 API URL 自动构造模型列表请求地址，并将返回结果展示在供应商模型列表中。

#### Scenario: 使用基础地址拉取模型列表
- **WHEN** 用户点击“获取模型列表”
- **THEN** 系统在基础 URL 后自动补充模型列表接口后缀，成功请求后展示返回的模型列表

#### Scenario: 基础地址来源于无 /v1 输入
- **WHEN** 用户最初输入的是 `https://api.deepseek.com/`
- **THEN** 系统仍可基于规范化后的地址成功请求模型列表并展示结果

### Requirement: 聊天请求自动补充聊天接口后缀
系统 SHALL 基于已保存的基础 API URL 自动构造聊天请求地址，避免要求用户手工填写完整聊天接口路径。

#### Scenario: 发起聊天请求
- **WHEN** 用户使用该供应商进行聊天
- **THEN** 系统自动在基础 URL 后补充聊天接口后缀并正常发送请求

#### Scenario: 不重复拼接聊天后缀
- **WHEN** 已保存地址本身已包含聊天接口路径或等价规范信息
- **THEN** 系统不会生成重复的 `/chat/completions/chat/completions` 路径

## MODIFIED Requirements
### Requirement: 供应商 API URL 输入框行为
供应商 API URL 输入框保存的应是可复用的基础 API 地址，系统负责在不同场景下补充各自所需的接口后缀，而不是要求用户自己维护完整终端接口路径。

#### Scenario: 用户查看已保存配置
- **WHEN** 用户重新打开供应商详情面板
- **THEN** 输入框中显示的是规范化后的基础 API 地址，且该地址能同时支持模型列表获取与聊天请求

## REMOVED Requirements
### Requirement: 保存时固定追加完整聊天接口路径
**Reason**: 该行为会导致 `/v1` 场景下出现重复拼接，不利于模型列表和聊天共用同一基础地址。
**Migration**: 将现有保存逻辑迁移为“先规范化基础地址，再按功能场景动态补充后缀”。
