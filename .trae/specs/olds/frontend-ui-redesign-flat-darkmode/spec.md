# 前端全局UI扁平化与黑白模式重构 Spec

## Why
当前前端UI尚未形成统一的“极简、扁平化”设计语言，且不支持全局的白天黑夜模式（Dark Mode）切换。部分深色样式被硬编码在全局变量中，且各个功能模块中存在边框和阴影风格不统一的问题。为了提升用户体验，满足“不能过于花里胡哨、支持白天黑夜模式、风格统一、扁平化UI”的核心诉求，需要对前端全局样式和组件进行系统性重构。

## What Changes
- **设计系统升级**：引入全局的主题系统，支持自动检测系统偏好以及手动切换白天黑夜模式。
- **全局CSS重构**：清理 `global.css` 中硬编码的颜色，全面替换为支持双主题的 CSS 变量（如 `--color-bg`, `--color-text`, `--color-bg-secondary`），并通过 `.dark` 类实现主题级联。
- **扁平化UI规范**：去除多余的卡片边框、重度阴影，改用柔和的背景色区分视觉层级，确保风格极简。
- **统一组件交互**：全局统一按钮（Button）、输入框（Input）、选择框（Select）、卡片（Card）等基础组件的样式，移除默认的强边框，采用背景悬停效果。
- **侧边栏与布局**：重构 Sidebar，底部添加主题切换开关，支持手动切换白天黑夜模式。
- **页面适配**：全局更新 Chat、Dashboard、Plugins、Skills、Memory、Billing 等功能页的 CSS 模块，适配新的 CSS 变量系统。

## Impact
- Affected specs: UI styling, Theme toggling, UX consistency.
- Affected code: 
  - `frontend/src/styles/global.css`
  - `frontend/src/shared/store/themeStore.ts` (新增的主题状态管理)
  - `frontend/src/App.tsx` (主题提供者初始化)
  - `frontend/src/shared/components/Sidebar/Sidebar.tsx` 及对应的 CSS
  - 所有 `features/**/*.module.css` 样式文件

## ADDED Requirements
### Requirement: 白天黑夜模式切换 (Dark Mode Toggle)
系统应支持全局的白天黑夜模式切换，并在本地持久化用户的偏好设置。
#### Scenario: 切换主题
- **WHEN** 用户在侧边栏点击“切换主题”按钮
- **THEN** 系统切换当前的主题（`html` 节点添加/移除 `.dark` 类），并平滑过渡全局颜色。

## MODIFIED Requirements
### Requirement: 极简扁平化UI (Minimalist Flat UI)
全局 UI 组件（按钮、输入框、卡片）必须遵循无边框或弱边框、无强阴影的设计原则。
#### Scenario: 页面浏览
- **WHEN** 用户浏览各个功能页面时
- **THEN** 页面的视觉层级主要由背景颜色（如 `var(--color-bg-secondary)`）来区分，而不是强烈的卡片边框，且界面不过于花里胡哨。