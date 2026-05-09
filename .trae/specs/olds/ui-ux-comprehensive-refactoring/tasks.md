# Tasks
- [x] Task 1: 重新定位 UserFloatingArea
  - [x] SubTask 1.1: 修改 `Sidebar.tsx`，将 `UserFloatingArea` 组件引入并放置在 `nav` 容器的最底部。
  - [x] SubTask 1.2: 更新 `UserFloatingArea` 及其相关的 CSS Modules，移除绝对定位（如 `fixed` 或 `absolute`），并调整其样式以适应侧边栏的宽度和背景。
  - [x] SubTask 1.3: 更新 `Sidebar` 的 CSS，确保 `nav` 容器使用 Flexbox 布局（如 `display: flex; flex-direction: column; justify-content: space-between;` 或 `margin-top: auto`）以将用户区域推至底部。
- [x] Task 2: 全面视觉优化 - 色彩与排版
  - [x] SubTask 2.1: 优化全局 CSS 变量（如主色调、背景色、文本色、边框色），增强对比度和现代感（参考 `ui-ux-pro-max` 指南，避免低对比度）。
  - [x] SubTask 2.2: 改进字体排版层次，调整标题、正文、辅助文本的字号、字重及行高。
- [ ] Task 3: 交互体验与动效增强
  - [x] SubTask 3.1: 为所有可交互元素（按钮、链接、侧边栏菜单项）添加平滑的过渡动效（`transition`）和明确的悬停（hover）、激活（active）状态反馈。
  - [x] SubTask 3.2: 确保不使用 emoji 作为 UI 图标，统一使用 SVG 图标，并保证图标大小一致。
- [x] Task 4: 响应式与布局重构
  - [x] SubTask 4.1: 审查并重构主应用布局结构（Main Layout），确保内容区域的内边距和最大宽度设置合理。
  - [x] SubTask 4.2: 优化侧边栏和主内容区在不同屏幕尺寸下的响应式表现（如移动端下的抽屉式侧边栏或合理的折叠逻辑）。
- [x] Task 5: 代码清理与性能优化
  - [x] SubTask 5.1: 移除无用的样式代码，确保组件拆分合理，代码结构清晰。
  - [x] SubTask 5.2: 运行前端 TypeScript 检查和 ESLint 检查，确保无类型错误和规范警告。

# Task Dependencies
- [Task 1] 是重构的起点，需优先完成以解决核心的布局调整需求。
- [Task 2] 和 [Task 3] 可并行或在其后进行，为整个应用提供视觉和交互基础。
- [Task 4] 依赖于基础布局的确定。
- [Task 5] 是最终的收尾工作。
