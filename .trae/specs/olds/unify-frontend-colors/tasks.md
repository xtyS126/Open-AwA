# Tasks
- [x] Task 1: 建立前端颜色基线与替换清单
  - [x] SubTask 1.1: 扫描 `frontend/src` 中所有颜色字面量（HEX/RGBA/命名色）
  - [x] SubTask 1.2: 区分“通用色、语义状态色、品牌色、图表色”
  - [x] SubTask 1.3: 产出需替换文件清单与优先级（先核心页面后次要页面）

- [x] Task 2: 扩展并规范全局颜色令牌
  - [x] SubTask 2.1: 在 `global.css` 补齐语义令牌（success/error/warning/info 的前景与背景）
  - [x] SubTask 2.2: 补齐图表令牌（grid/axis/primary/secondary）
  - [x] SubTask 2.3: 补齐遮罩与深色面板令牌（overlay/surface-dark/text-on-dark）
  - [x] SubTask 2.4: 保持对现有变量兼容，不破坏已接入页面

- [x] Task 3: 统一核心页面与组件颜色
  - [x] SubTask 3.1: 改造 `BillingPage.css`，替换中性色与状态色硬编码
  - [x] SubTask 3.2: 改造 `ChatPage.css`，统一错误提示、按钮与状态色
  - [x] SubTask 3.3: 改造 `ExperiencePage.css`，统一多状态标签配色
  - [x] SubTask 3.4: 改造 `SkillModal.css`，统一弹窗深色主题色值
  - [x] SubTask 3.5: 改造 `PluginDebugPanel.css` 与 `PluginsPage.css`，统一状态与强调色

- [x] Task 4: 清理 TSX 内联颜色与图表颜色
  - [x] SubTask 4.1: 改造 `App.tsx`、`SettingsPage.tsx` 的内联颜色为 CSS 变量或类名
  - [x] SubTask 4.2: 改造 `DashboardPage.tsx` 图表颜色为统一映射来源
  - [x] SubTask 4.3: 改造 `BillingPage.tsx` 图表与空态文字颜色为统一映射来源

- [x] Task 5: 品牌色集中治理
  - [x] SubTask 5.1: 对 provider badge 颜色建立集中映射（文件内集中常量或变量块）
  - [x] SubTask 5.2: 校验品牌色之外不存在非必要硬编码

- [x] Task 6: 质量验证与回归
  - [x] SubTask 6.1: 重新扫描硬编码颜色，确认核心页面通用色已收敛
  - [x] SubTask 6.2: 运行前端类型检查（`npm run typecheck`）
  - [x] SubTask 6.3: 人工检查关键页面视觉一致性（Chat/Dashboard/Billing/Settings/Skills/Plugins）

# Task Dependencies
- [Task 2] 依赖 [Task 1]
- [Task 3] 依赖 [Task 1] 和 [Task 2]
- [Task 4] 依赖 [Task 2]
- [Task 5] 依赖 [Task 2] 和 [Task 3]
- [Task 6] 依赖 [Task 3]、[Task 4]、[Task 5]
