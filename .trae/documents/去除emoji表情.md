# 去除代码中的 Emoji 表情计划

## 需求概述
根据项目规则，需要去除前端代码中的所有 emoji 表情，使用 SVG 图标或文本标签代替。

## 受影响文件
1. `frontend/src/components/Sidebar.tsx` - 侧边栏菜单图标
2. `frontend/src/pages/ChatPage.tsx` - 聊天空状态欢迎语

## Emoji 替换方案

### Sidebar.tsx
| 位置 | 当前 Emoji | 替换方案 |
|------|-----------|---------|
| logo-icon | 🦞 | 使用 SVG 机械爪图标 |
| 聊天 | 💬 | 使用 SVG 聊天气泡图标 |
| 概览 | 📊 | 使用 SVG 图表图标 |
| 使用情况 | 📈 | 使用 SVG 趋势图标 |
| 技能 | ⚡ | 使用 SVG 闪电图标 |
| 插件 | 🔌 | 使用 SVG 插头图标 |
| 记忆 | 🧠 | 使用 SVG 大脑图标 |
| 设置 | ⚙️ | 使用 SVG 齿轮图标 |

### ChatPage.tsx
| 位置 | 当前 Emoji | 替换方案 |
|------|-----------|---------|
| 空状态欢迎语 | 👋 | 移除 emoji，直接使用文本 |

## 实施步骤

### 1. 修改 Sidebar.tsx
- [ ] 导入 SVG 图标组件（内联 SVG）
- [ ] 替换 logo-icon 的 emoji 为 SVG 图标
- [ ] 替换 menuItems 中的所有 emoji 为 SVG 图标
- [ ] 添加相应的 CSS 样式

### 2. 修改 ChatPage.tsx
- [ ] 移除空状态欢迎语中的 emoji
- [ ] 保持纯文本欢迎语

## 预期效果
- 所有 emoji 表情被移除
- 使用内联 SVG 图标替代，保持视觉一致性
- 代码符合项目规范（除用户需要外不使用 emoji）
