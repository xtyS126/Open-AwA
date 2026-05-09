# 计费配置供应商预填充 Spec

## Why

当前"计费配置"页面的供应商目录仅展示已在数据库中手动创建的 `ModelConfiguration` 记录，而 `pricing_data.json` 中已为 7 个厂商（openai / anthropic / google / deepseek / alibaba / moonshot / zhipu）预置了完整的模型价格数据。用户需要逐个手动"新增供应商"才能在模型中看到这些厂商，增加了无谓的配置成本。

## What Changes

- 后端 `get_provider_catalog()` 改为合并两路数据源：数据库已有配置 + `pricing_data.json` 中的默认定价厂商
- 在计费配置 Tab 中，来自 JSON 的供应商无需手动创建即可在价格表中展示其模型
- 新增供应商弹窗中，供应商标识输入框改为下拉选择（预置已知厂商 + 自定义输入），选中已知厂商后自动填充显示名称和默认模型 
- **联动**：在"计费配置"的模型价格表中，每行模型价格与其厂商关联，且可直接编辑价格（当前已有编辑能力，本次确保所有厂商模型都可用）
- **BREAKING**: 无

## Impact

- Affected specs: 无已有 spec 受影响
- Affected code:
  - `backend/billing/pricing_manager.py` — 改造 `get_provider_catalog()`，合并 JSON 数据源
  - `backend/billing/routers/billing.py` — 新增端点或改造 `/providers` 返回增强数据
  - `frontend/src/features/settings/SettingsPage.tsx` — "新增供应商"弹窗改为下拉选择已知厂商
  - `frontend/src/features/settings/modelsApi.ts` — 新增获取已知厂商列表的 API 类型

## ADDED Requirements

### Requirement: 供应商目录自动包含定价 JSON 中的厂商

系统 SHALL 在 `/billing/providers` 接口的返回中自动包含 `pricing_data.json` 中已定义但尚未在数据库中创建配置的厂商信息，使其在供应商列表中可见。

#### Scenario: 定价 JSON 包含 openai，但数据库中无 openai 配置

- **GIVEN** `pricing_data.json` 包含供应商 `openai` 的多个模型定价
- **AND** 数据库中不存在 `openai` 的活跃 `ModelConfiguration`
- **WHEN** 前端调用 `GET /billing/providers`
- **THEN** 返回的 `providers` 列表中包含 `openai`（标记 `source: "pricing_json"`）
- **AND** 该条目包含 `selected_models`（即 JSON 中该厂商所有模型名列表）

#### Scenario: 定价 JSON 与数据库都有同一厂商

- **GIVEN** `pricing_data.json` 包含 `deepseek`
- **AND** 数据库已存在 `deepseek` 的活跃配置
- **WHEN** 前端调用 `GET /billing/providers`
- **THEN** 返回的 `deepseek` 条目以数据库配置为准（`source: "database"`）
- **AND** `selected_models` 为数据库配置与 JSON 模型的并集

### Requirement: 新增供应商弹窗支持已知厂商快速选择

系统 SHALL 在"新增供应商"弹窗中将供应商标识从自由文本改为下拉选择框，预置所有已知厂商 ID，同时保留自定义输入能力。

#### Scenario: 用户选择已知厂商 "openai"

- **WHEN** 用户在新增供应商弹窗的下拉框中选择 `openai`
- **THEN** 系统自动填充显示名称为 "OpenAI"
- **AND** 默认模型为空（由用户在后续模型管理中配置）

#### Scenario: 用户输入自定义厂商 ID

- **WHEN** 用户选择 "自定义" 或直接输入不在预置列表中的标识
- **THEN** 表现与现有行为一致（手动填写各项）

## MODIFIED Requirements

### Requirement: 供应商目录获取

**原行为**: `get_provider_catalog()` 仅查询数据库中活跃的 `ModelConfiguration` 记录。
**新行为**: 在上述基础上，额外合并 `pricing_data.json` 中每个 `provider` 的唯一值，将未在数据库出现过的厂商追加到结果末尾。

## REMOVED Requirements

无。

## 附录：定价 JSON 文件路径

- **模型价格数据**: `d:\代码\Open-AwA\backend\config\pricing\pricing_data.json`
- **模型能力参数**: `d:\代码\Open-AwA\backend\config\pricing\model_capabilities.json`
- **默认模型配置**: `d:\代码\Open-AwA\backend\config\pricing\default_configurations.json`
- **旧版配置键映射**: `d:\代码\Open-AwA\backend\config\pricing\legacy_config_keys.json`

