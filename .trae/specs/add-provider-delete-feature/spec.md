# 供应商删除功能 Spec

## Why
当前 API 配置页面支持新增和编辑供应商，但缺少删除供应商能力。用户在误创建、停用或迁移供应商时无法在页面直接清理，导致列表堆积和管理成本上升。需要提供明确、可确认、可回退到稳定状态的供应商删除流程。

## What Changes
- 在 API 配置页面增加“删除供应商”操作入口，作用于当前选中的供应商
- 删除前增加二次确认，避免误删
- 删除后刷新供应商列表并自动切换到可用供应商或空状态
- 后端补充按供应商维度的删除接口，统一处理该供应商下配置的失活
- 删除失败时展示明确错误信息，页面状态保持一致

## Impact
- Affected specs: 设置页 API 配置、供应商管理
- Affected code:
  - `frontend/src/pages/SettingsPage.tsx`
  - `frontend/src/pages/SettingsPage.css`
  - `frontend/src/services/modelsApi.ts`
  - `backend/billing/pricing_manager.py`
  - `backend/billing/routers/billing.py`
  - `backend/tests/test_pricing_manager.py`

## ADDED Requirements

### Requirement: 供应商删除入口
系统 SHALL 在 API 配置页右侧详情操作区提供删除当前供应商的入口。

#### Scenario: 已选择供应商时显示删除能力
- **GIVEN** 用户已在左侧列表选中一个供应商
- **WHEN** 右侧详情面板完成加载
- **THEN** 用户可见“删除供应商”按钮
- **AND** 删除操作应与“获取模型列表/保存供应商配置”并列展示

### Requirement: 删除前确认
系统 SHALL 在执行删除前进行明确确认，避免误操作。

#### Scenario: 用户触发删除
- **WHEN** 用户点击“删除供应商”
- **THEN** 系统展示确认交互并说明影响范围（当前供应商配置将被删除）
- **AND** 用户取消时不发送删除请求

### Requirement: 按供应商删除后端能力
系统 SHALL 提供按供应商标识删除配置的后端接口。

#### Scenario: 删除存在的供应商
- **GIVEN** 指定供应商存在至少一条激活配置
- **WHEN** 前端调用删除接口
- **THEN** 后端将该供应商下激活配置标记为失活并返回成功

#### Scenario: 删除不存在的供应商
- **GIVEN** 指定供应商无可删除配置
- **WHEN** 前端调用删除接口
- **THEN** 后端返回 404，并提供可读错误信息

### Requirement: 删除后的前端状态恢复
系统 SHALL 在删除成功后保持页面处于可继续操作的稳定状态。

#### Scenario: 删除成功后刷新列表
- **WHEN** 删除请求成功
- **THEN** 左侧供应商列表立即刷新
- **AND** 若仍有供应商则自动选中一个可用项并加载详情
- **AND** 若无供应商则显示空状态并清空右侧表单

#### Scenario: 删除失败
- **WHEN** 删除请求失败
- **THEN** 页面保留原选中项与原表单内容
- **AND** 展示失败提示，不应误清空用户输入

## MODIFIED Requirements

### Requirement: API 配置页供应商操作集合
原“仅支持新增和保存”改为“支持新增、保存、删除”的供应商管理闭环。

#### Scenario: 操作闭环
- **WHEN** 用户进入 API 配置页
- **THEN** 用户可完成供应商新增、编辑保存、删除的完整生命周期管理
