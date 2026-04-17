# 插件导航迁移与配置面板 Spec

## Why
当前插件入口仅为单一页面链接，缺少管理与配置分层，导致插件导入、批量操作、配置编辑和实时生效能力分散且不可扩展。需要统一为嵌套路由与可扩展配置面板，以满足可维护性、性能和可测试性要求。

## What Changes
- 将侧边栏 `插件` 入口迁移为可展开导航分支，包含 `插件管理` 与 `插件配置` 两个子路由入口。
- 新增 `/plugins/manage` 页面：支持插件导入（上传 ZIP / 远程 URL）、列表展示、简介查看、关键词搜索、批量删除、启用/禁用状态显示与操作反馈。
- 新增 `/plugins/config/:pluginId` 页面：根据插件 `schema.json` 动态生成配置表单，支持 `input`、`select`、`switch`、`code-editor`、`file-picker` 五类字段。
- 新增配置辅助操作：`重置默认`、`导出配置`、`导入配置`，三项操作均需二次确认弹窗。
- 插件配置持久化目标为插件独立目录 `${pluginId}/config.json`，保存后无需刷新页面即可实时生效。
- 前端异步请求统一抽象为 hooks，并内置 `loading`、`error`、`retry` 状态管理。
- 增加单元测试，覆盖导入解析、动态表单渲染、配置持久化三大核心场景，覆盖率目标不低于 80%。
- 补充 README：目录结构、环境变量、插件包格式（zip 内含 `index.js`、`schema.json`、`README.md`）与本地调试步骤。
- **BREAKING**：插件导航信息架构发生调整，旧单页插件入口行为变更为分支导航与子路由承载。

## Impact
- Affected specs: 插件侧边栏导航、插件管理工作流、插件配置与持久化、前端异步状态规范、插件文档交付、前端性能验收。
- Affected code: `frontend/src/layout` 侧边栏与路由配置、`frontend/src/features/plugins` 页面与 hooks、插件 API 适配层、测试目录、项目 README。

## ADDED Requirements
### Requirement: 插件分支导航与嵌套路由
系统 SHALL 提供 `插件` 可展开分支导航，并通过嵌套路由暴露 `/plugins/manage` 与 `/plugins/config/:pluginId`。

#### Scenario: 进入插件管理页
- **WHEN** 用户点击侧边栏 `插件` 分支中的 `插件管理`
- **THEN** 系统进入 `/plugins/manage` 并展示插件管理页面

#### Scenario: 进入插件配置页
- **WHEN** 用户在管理页选择某插件并进入配置
- **THEN** 系统进入 `/plugins/config/:pluginId` 并加载目标插件配置面板

### Requirement: 插件管理页面能力
系统 SHALL 在 `/plugins/manage` 提供导入、删除、列表、检索和简介查看能力，并在关键操作后提供 Toast 反馈。

#### Scenario: 远程 URL 导入插件
- **WHEN** 用户输入合法远程 URL 并确认导入
- **THEN** 系统完成导入、刷新列表并显示成功反馈；失败时显示错误反馈与重试入口

#### Scenario: 批量删除插件
- **WHEN** 用户选择多个插件并执行删除
- **THEN** 系统完成批量删除并即时更新列表，无需手动刷新

### Requirement: 基于 schema 的动态配置表单
系统 SHALL 依据插件 `schema.json` 自动渲染配置表单，并支持 `input`、`select`、`switch`、`code-editor`、`file-picker` 字段类型。

#### Scenario: 字段实时校验
- **WHEN** 用户修改任一可编辑字段
- **THEN** 系统实时执行校验并在界面展示错误信息，禁止提交非法配置

#### Scenario: 保存并持久化配置
- **WHEN** 用户点击保存且校验通过
- **THEN** 系统将配置写入 `${pluginId}/config.json`，并使变更在当前会话实时生效

### Requirement: 配置辅助操作与确认机制
系统 SHALL 提供 `重置默认`、`导出配置`、`导入配置` 按钮，并在执行前展示二次确认弹窗。

#### Scenario: 重置默认配置
- **WHEN** 用户点击 `重置默认` 并在确认弹窗中确认
- **THEN** 系统恢复默认值并持久化到 `${pluginId}/config.json`

### Requirement: 异步 hooks 标准化
系统 SHALL 将插件管理与配置相关的异步行为封装为 hooks，且每个 hook 提供 `loading`、`error`、`retry` 状态能力。

#### Scenario: 异步请求失败重试
- **WHEN** 任一插件异步请求失败
- **THEN** UI 显示错误状态并允许用户通过 `retry` 重试请求

### Requirement: 测试与文档交付
系统 SHALL 提供不少于 80% 的相关单元测试覆盖率，并交付插件功能 README。

#### Scenario: 测试门禁
- **WHEN** 执行前端测试与覆盖率统计
- **THEN** 导入解析、配置表单渲染、配置持久化三类场景均有测试，且覆盖率达到目标

### Requirement: 性能与实时生效验收
系统 SHALL 满足导入耗时、首渲染性能与内存稳定性验收指标。

#### Scenario: 性能验收
- **WHEN** 在 Chrome 90 模拟 4G 与验收约束下执行测试
- **THEN** 满足插件包 ≤ 50MB 导入 < 3s、配置表单首渲染 < 300ms、连续快照内存增长 ≤ 1MB

## MODIFIED Requirements
### Requirement: 侧边栏插件入口
系统 SHALL 将原单一 `插件` 链接修改为可展开分支导航，分支内至少包含 `插件管理` 与 `插件配置` 子入口，并与嵌套路由保持一致。

## REMOVED Requirements
### Requirement: 无
**Reason**: 本次变更以增强与重构为主，不移除既有能力。
**Migration**: 不适用。
