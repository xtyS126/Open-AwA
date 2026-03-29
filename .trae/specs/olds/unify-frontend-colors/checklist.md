# Checklist

## 1. 颜色规范与令牌
- [x] 已建立颜色分类（通用色/语义色/品牌色/图表色）
- [x] `global.css` 已补齐语义状态色（success/error/warning/info）
- [x] `global.css` 已补齐图表色令牌（grid/axis/primary/secondary）
- [x] 已定义遮罩与深色面板相关令牌
- [x] 新增令牌与现有变量保持兼容

## 2. 页面与组件统一
- [x] `BillingPage.css` 通用硬编码颜色已替换为变量
- [x] `ChatPage.css` 通用硬编码颜色已替换为变量
- [x] `ExperiencePage.css` 通用硬编码颜色已替换为变量
- [x] `SkillModal.css` 颜色已统一为变量驱动
- [x] `PluginDebugPanel.css` 与 `PluginsPage.css` 通用硬编码已替换

## 3. TSX 与图表
- [x] `App.tsx` 内联颜色已清理
- [x] `SettingsPage.tsx` 内联颜色已清理
- [x] `DashboardPage.tsx` 图表颜色来源已统一
- [x] `BillingPage.tsx` 图表与空态颜色来源已统一

## 4. 品牌色治理
- [x] provider badge 颜色已集中管理
- [x] 品牌色仅在必要区域存在
- [x] 非品牌区域无散落硬编码通用色

## 5. 验证
- [x] 核心页面视觉风格保持一致且可读性正常
- [x] 前端类型检查通过（`npm run typecheck`）
- [x] 颜色字面量复扫结果符合预期（仅保留必要例外）
