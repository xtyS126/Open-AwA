# 通讯配置独立页面规范

## Why
当前“通讯配置”通过 `/settings?tab=communication` 挂载在设置页内部，页面容器仍展示“设置”头部与设置 Tabs，导致用户感知为“设置子项”而不是“独立功能页面”。需要将通讯配置拆分为独立路由和独立页面组件。

## What Changes
- 新增独立通讯配置页面路由（如 `/communication`），不再复用设置页容器。
- 将微信 Clawbot 配置 UI 从 `SettingsPage` 抽离到独立页面组件。
- 侧边栏“通讯配置”入口改为直达独立页面。
- 保留原有微信配置保存与健康检查能力，接口契约不变。
- 调整测试用例，覆盖独立页面渲染与交互。

## Impact
- Affected specs: 前端路由、导航结构、通讯配置页面结构、前端测试
- Affected code: `frontend/src/App.tsx`、`frontend/src/components/Sidebar.tsx`、`frontend/src/pages/SettingsPage.tsx`、`frontend/src/pages/*`、`frontend/src/__tests__/*`

## ADDED Requirements
### Requirement: 通讯配置独立页面
系统 SHALL 提供独立的“通讯配置”页面，页面主体仅展示通讯相关功能，不包含设置页 Tabs 容器。

#### Scenario: 从侧边栏进入通讯配置
- **WHEN** 用户点击侧边栏“通讯配置”
- **THEN** 页面跳转到独立通讯路由并显示通讯配置页面

#### Scenario: 页面内容独立
- **WHEN** 用户访问通讯配置页面
- **THEN** 页面标题与主体内容仅与通讯配置相关，不显示设置页头部 Tabs

### Requirement: 功能行为保持一致
系统 SHALL 保持微信 Clawbot 配置保存、必填校验、健康检查行为与现有实现一致。

#### Scenario: 保存配置
- **WHEN** 用户在独立通讯页面提交合法配置
- **THEN** 系统成功保存并反馈保存结果

#### Scenario: 健康检查
- **WHEN** 用户触发“测试连接”
- **THEN** 页面按结构化结果显示成功或失败信息及建议

## MODIFIED Requirements
### Requirement: 导航入口映射
侧边栏中的“通讯配置”入口 SHALL 从设置页查询参数模式迁移为独立页面路由模式。

## REMOVED Requirements
### Requirement: 通过 settings tab 渲染通讯配置
**Reason**: 通讯配置需要独立页面语义和独立页面容器，避免与设置页内容混淆。
**Migration**: 保留旧路由的兼容跳转（可选），并将导航入口统一切换到独立路由。
