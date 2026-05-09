# 模型模态展示 Spec

## Why

当前模型价格表格只展示价格和上下文信息，用户无法直观了解每个模型支持哪些输入模态（文本、图像、音频、视频）。通过在每个模型行添加模态标签，用户可以快速识别模型的多模态能力，辅助模型选择和成本估算。

## What Changes

### 后端变更

1. **ModelPricing 表新增字段**
   - `supports_vision: bool` — 是否支持图像输入（视觉理解）
   - `is_multimodal: bool` — 是否支持多模态（同时支持文本+图像/音频/视频中的至少一种非文本模态）

2. **pricing_manager.py `initialize_default_pricing()` 扩展**
   - 创建 ModelPricing 记录后，从 `model_capabilities.json` 查找对应模型的 `supports_vision` 和 `is_multimodal` 并回填
   - 现有记录通过迁移脚本或重新初始化补齐

3. **`/billing/models` API 响应扩展**
   - 每个 model 对象新增 `supports_vision: bool` 和 `is_multimodal: bool` 字段

### 前端变更

4. **billingApi.ts `ModelPricing` 接口扩展**
   - 新增 `supports_vision: boolean` 和 `is_multimodal: boolean`

5. **SettingsPage.tsx 价格表格新增"模态"列**
   - 在"模型"列后插入"模态"列
   - 根据 `supports_vision` 和 `is_multimodal` 渲染标签：
     - 仅文本 → 显示 "文本"
     - 视觉支持 → 显示 "文本 + 图像"
     - 多模态 → 显示 "文本 + 图像 + 音视频"
   - 标签使用彩色圆角 badge 样式

6. **SettingsPage.module.css 新增模态标签样式**
   - `.modality-badge`: 基础 badge 样式
   - `.modality-text`: 仅文本 — 灰色
   - `.modality-vision`: 视觉支持 — 蓝色
   - `.modality-multimodal`: 多模态 — 紫色

### 数据变更

7. **model_capabilities.json 按厂家补齐模态数据**
   - 确保 `supports_vision` 和 `is_multimodal` 在所有条目中准确
   - 按厂家逐个确认：alibaba(阿里通义千问)、openai、anthropic、google、deepseek、moonshot(kimi)、zhipu(智谱AI)

## Impact

- **受影响的能力**: 模型价格配置、模型管理、定价数据初始化
- **受影响的前端文件**:
  - `frontend/src/features/billing/billingApi.ts`
  - `frontend/src/features/settings/SettingsPage.tsx`
  - `frontend/src/features/settings/SettingsPage.module.css`
- **受影响的后端文件**:
  - `backend/billing/models.py`
  - `backend/billing/pricing_manager.py`
  - `backend/billing/routers/billing.py`
- **受影响的数据文件**:
  - `backend/config/pricing/model_capabilities.json`
- **无需变更**: `pricing_data.json`、`default_configurations.json`（模态数据不从定价数据派生）

## ADDED Requirements

### Requirement: 模态信息展示

系统 SHALL 在模型价格表格中为每个模型行展示其支持的输入模态能力。

#### Scenario: 成功展示模态标签
- **GIVEN** 用户打开设置页面的"模型价格配置"选项卡
- **WHEN** 价格表格渲染完成
- **THEN** 每个模型行的"模型"列之后显示"模态"列
- **AND** 模态列显示对应的标签（文本 / 文本+图像 / 文本+图像+音视频）

#### Scenario: 模态数据自动填充
- **GIVEN** 管理员调用 `/billing/initialize-pricing` 接口初始化定价数据
- **WHEN** 系统创建新的 ModelPricing 记录
- **THEN** 系统自动从 `model_capabilities.json` 读取对应模型的 `supports_vision` 和 `is_multimodal` 值并写入数据库
- **AND** 已存在的 ModelPricing 记录保持不变

#### Scenario: 按厂家逐个确认模态数据
- **GIVEN** `model_capabilities.json` 包含所有 7 个厂家的 75 个模型条目
- **WHEN** 检查每个条目的 `supports_vision` 和 `is_multimodal` 字段
- **THEN** 每个条目的值应与其实际模型能力一致
- **AND** 以下厂家按顺序逐个确认：alibaba -> openai -> anthropic -> google -> deepseek -> moonshot -> zhipu
