# Tasks

- [ ] Task 1: 建立基础主题系统与全局CSS变量
  - [ ] SubTask 1.1: 重写 `global.css`，定义 `:root`（白天模式）和 `.dark`（黑夜模式）下的全套语义化 CSS 变量（背景、文本、边框、主色）。
  - [ ] SubTask 1.2: 更新基础元素（body, button, input, textarea）的全局样式，实现扁平化无边框/弱边框设计，并添加颜色平滑过渡动画（如 `transition: background-color 0.3s, color 0.3s`）。
  - [ ] SubTask 1.3: 在 `frontend/src/shared/store/` 下创建 `themeStore.ts`（使用 Zustand），支持读取系统偏好并持久化到 localStorage，并在 `App.tsx` 动态挂载 `.dark` 类到 `html` 标签。

- [ ] Task 2: 侧边栏重构与主题切换入口
  - [ ] SubTask 2.1: 重构 `Sidebar.tsx` 及样式，采用扁平化设计，移除右侧硬边框，改用背景色区分。
  - [ ] SubTask 2.2: 在 Sidebar 底部增加一个美观的主题切换按钮（使用 SVG 图标或文字），支持手动切换白天/黑夜模式，并禁止使用 Emoji。

- [ ] Task 3: 核心交互页面适配（Chat 与 Dashboard）
  - [ ] SubTask 3.1: 升级 `ChatPage` 与 `CommunicationPage`，气泡和输入框采用扁平化色块（`--color-bg-secondary`），移除生硬边框。
  - [ ] SubTask 3.2: 升级 `DashboardPage`，数据卡片和图表区域适配扁平化规范与暗色模式。

- [ ] Task 4: 配置与管理页面适配（Plugins, Skills, Settings, Memory, Billing, Experiences）
  - [ ] SubTask 4.1: 升级 `PluginsPage`、`SkillsPage` 与 `SettingsPage`，统一表单输入框、下拉框、开关和列表项的扁平化样式与悬停效果。
  - [ ] SubTask 4.2: 升级 `MemoryPage`、`BillingPage` 和 `ExperiencePage`，确保表格、卡片和标签在黑夜模式下的对比度与可读性，移除花里胡哨的设计。

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 1]