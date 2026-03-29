# 供应商配置页面修复与新建弹窗 Spec

## Why
当前供应商配置页面存在两个问题：1. 详情面板中的 API URL 字段消失，导致用户无法编辑供应商的接口地址；2. "新建供应商"的入口挤在狭小的 `div` 中，交互空间局促，体验不佳。应当修复字段缺失，同时将新建供应商改为独立的弹窗表单。

## What Changes
- 修复供应商详情面板中 API URL 字段的展示与绑定
- 将"新建供应商"入口改为弹窗表单，包含供应商标识、显示名称、图标地址、API URL 等必填/选填字段
- 弹窗提交后自动选中新创建的供应商条目
- 保持现有的双栏布局与侧边栏交互不变

## Impact
- Affected specs: 设置页 API 配置、供应商管理
- Affected code:
  - `frontend/src/pages/SettingsPage.tsx`
  - `frontend/src/pages/SettingsPage.css`
  - `frontend/src/services/billingApi.ts`

## ADDED Requirements

### Requirement: 供应商详情面板 API URL 字段完整
系统 SHALL 在右侧供应商详情面板中完整展示 API URL 输入框，并与后端接口正确绑定。

#### Scenario: 查看已有供应商
- **WHEN** 用户点击左侧供应商条目
- **THEN** 右侧面板应展示供应商标识、显示名称、图标地址、API URL、API Key 等全部字段
- **AND** API URL 字段应可编辑

### Requirement: 新建供应商弹窗
系统 SHALL 提供弹窗式表单用于新建供应商，而非在狭小区域内内联创建。

#### Scenario: 打开新建弹窗
- **WHEN** 用户点击"新增供应商"按钮
- **THEN** 系统应弹出模态框居中展示
- **AND** 弹窗内包含供应商标识、显示名称、图标地址（可选）、API URL（可选）等输入字段
- **AND** 弹窗提供"取消"和"确认创建"两个操作

#### Scenario: 填写并提交新建表单
- **WHEN** 用户填写供应商标识等必填字段后点击"确认创建"
- **THEN** 系统应调用后端接口创建供应商
- **AND** 创建成功后关闭弹窗并选中新供应商条目
- **AND** 左侧列表应实时更新

#### Scenario: 取消新建
- **WHEN** 用户在弹窗中点击"取消"或点击遮罩层
- **THEN** 弹窗应关闭且不触发任何创建操作

### Requirement: 弹窗表单验证
系统 SHALL 在创建前验证必填字段，并拒绝空标识提交。

#### Scenario: 标识为空时提交
- **WHEN** 用户未填写供应商标识就点击"确认创建"
- **THEN** 页面应显示明确错误提示且不发送请求

## MODIFIED Requirements

### Requirement: 新建供应商交互方式
原有的在 `div` 侧边栏内联创建供应商方式修改为弹窗表单方式。

#### Scenario: 从内联创建迁移到弹窗创建
- **WHEN** 用户点击"新增供应商"
- **THEN** 应出现弹窗而非内联展开
- **AND** 弹窗关闭后保持原有选中状态不变
