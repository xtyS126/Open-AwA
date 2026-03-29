# 前端颜色统一优化 Spec

## Why
当前前端颜色体系存在“全局变量 + 局部硬编码”并存的问题：
- 不同页面对文本色、边框色、背景色使用不一致，导致视觉风格分裂。
- 同类语义颜色（成功、警告、错误、图表色）在多个文件重复定义，维护成本高。
- TSX 内联样式和图表颜色字面量增多，难以统一迭代主题。

这会直接影响产品一致性、可维护性和后续主题扩展能力。

## What Changes
- 补齐并标准化全局颜色令牌（design tokens），覆盖基础色、语义状态色、图表色、遮罩与深色面板色。
- 将核心页面与组件中的通用硬编码颜色替换为 `var(--color-*)`。
- 统一 TSX 内联颜色写法，改为样式类或 CSS 变量。
- 统一图表颜色来源，避免在多个页面中重复书写不同字面量。
- 保留必要品牌色差异，但收敛到统一映射策略，减少散落硬编码。

## Impact
- Affected specs: 前端视觉一致性、样式可维护性
- Affected code:
  - `frontend/src/styles/global.css`
  - `frontend/src/pages/BillingPage.css`
  - `frontend/src/pages/ChatPage.css`
  - `frontend/src/pages/ExperiencePage.css`
  - `frontend/src/components/SkillModal.css`
  - `frontend/src/components/PluginDebugPanel.css`
  - `frontend/src/pages/PluginsPage.css`
  - `frontend/src/pages/SettingsPage.tsx`
  - `frontend/src/App.tsx`
  - `frontend/src/pages/DashboardPage.tsx`
  - `frontend/src/pages/BillingPage.tsx`

## ADDED Requirements

### Requirement: 全局颜色令牌完整性
系统 SHALL 在全局样式层提供完整且语义化的颜色令牌集合。

#### Scenario: 统一颜色入口
- **WHEN** 开发者需要为页面或组件设置颜色
- **THEN** 必须优先使用 `frontend/src/styles/global.css` 中定义的颜色变量
- **AND** 不应直接新增通用硬编码颜色

#### Scenario: 语义颜色覆盖
- **WHEN** 页面存在成功、警告、错误、信息提示等状态
- **THEN** 系统应提供对应语义颜色令牌（前景与背景）
- **AND** 同一语义状态在不同页面保持一致

#### Scenario: 图表颜色覆盖
- **WHEN** 页面包含 Recharts 图表（网格、坐标轴、折线、点）
- **THEN** 图表颜色应由统一令牌或统一映射常量提供
- **AND** 不应在多个图表组件中重复写死不同字面量

### Requirement: 通用硬编码颜色收敛
系统 SHALL 将核心页面中的通用硬编码颜色统一替换为全局变量。

#### Scenario: 页面样式收敛
- **WHEN** 核心页面（Billing/Chat/Experience/Plugins/Settings）加载样式
- **THEN** 文本、背景、边框、主按钮、状态提示使用全局变量
- **AND** 保持当前视觉层级与可读性不下降

#### Scenario: 组件样式收敛
- **WHEN** 弹窗与调试组件（SkillModal/PluginDebugPanel）使用颜色
- **THEN** 应优先复用统一令牌
- **AND** `var(--token, fallback)` fallback 仅在必要场景保留

### Requirement: 内联颜色最小化
系统 SHALL 减少 TSX 中的颜色字面量，统一颜色来源。

#### Scenario: App/Settings 内联样式
- **WHEN** `App.tsx`、`SettingsPage.tsx` 存在 `style={{ color: '#xxx' }}`
- **THEN** 应替换为 CSS 类或 `var(--color-*)`
- **AND** 不改变原有交互逻辑

### Requirement: 品牌色治理
系统 SHALL 对不可避免的品牌差异色建立可维护映射策略。

#### Scenario: provider badge 差异色
- **WHEN** 供应商徽标需保留品牌辨识度
- **THEN** 应通过集中映射定义品牌色（而非任意散落）
- **AND** 非品牌通用区域仍需使用全局语义令牌

## MODIFIED Requirements

### Requirement: 前端颜色使用规范
现有“可直接在页面样式写颜色值”的做法修改为“优先全局变量，硬编码仅限品牌差异与必要例外”。

#### Scenario: 新增样式开发
- **WHEN** 新增页面或组件样式
- **THEN** 默认从 design tokens 选取颜色
- **AND** 若引入新颜色，需先补充全局令牌再使用

## REMOVED Requirements

### Requirement: 页面可独立定义通用色值
**Reason**: 该模式导致颜色分裂、维护成本高、主题扩展困难。
**Migration**: 将既有通用色值统一迁移到全局令牌并完成引用替换。
