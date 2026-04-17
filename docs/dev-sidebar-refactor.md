# 侧边栏重构与页面布局优化 - 开发文档

## 1. 现状分析

### 1.1 当前侧边栏结构

当前侧边栏组件位于 `frontend/src/shared/components/Sidebar/Sidebar.tsx`，采用三级菜单结构：

- **一级**：菜单分组（控制、代理、设置）- 以 `group-title` 标签区分
- **二级**：菜单项（聊天、概览、技能、插件等）- 直接路由链接
- **三级**：子菜单项（仅插件有子菜单：插件管理、插件配置）

### 1.2 现存问题

1. **层级视觉区分不足**：一级分组标题仅为小字灰色文本，和二级菜单项视觉落差不够明显
2. **三级菜单仅插件使用**：只有插件有 children 子菜单，设计不具通用性
3. **页面布局无主次**：所有页面均采用全宽平铺布局，没有内容区域的主次划分
4. **折叠模式信息丢失**：折叠后分组标题完全消失，失去导航上下文
5. **图标单色无层级感**：所有图标等大、等色，缺乏视觉权重区分

### 1.3 涉及文件

| 文件 | 说明 |
|------|------|
| `src/shared/components/Sidebar/Sidebar.tsx` | 侧边栏组件 |
| `src/shared/components/Sidebar/Sidebar.module.css` | 侧边栏样式 |
| `src/styles/global.css` | 全局变量和布局 |
| `src/App.tsx` | 应用入口和布局容器 |
| `src/features/*/[Page].module.css` | 各页面样式 |

## 2. 重构目标

### 2.1 侧边栏改进

1. **一级分组**：增加分隔线和折叠控制，可点击展开/收起整个分组
2. **二级菜单项**：增加悬停过渡效果，Active 状态加左侧指示条
3. **三级子菜单**：独立展开/折叠动画，连接线视觉指引
4. **折叠模式**：显示 tooltip 提示，分组用分隔线区分
5. **整体视觉**：加强层级间距差异，优化活跃态和悬停态

### 2.2 页面布局改进

1. 统一所有页面为"页头 + 内容区"结构
2. 复杂页面（设置、插件配置）支持二级侧导航面板
3. 页面内容区适当加 `max-width`，保持大屏可读性

## 3. 具体实现方案

### 3.1 侧边栏 CSS 改进

```css
/* 一级分组 - 增加分隔线和展开控制 */
.group-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  padding: 8px 16px 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-text-tertiary);
  transition: color 0.2s;
}

.group-title:hover {
  color: var(--color-text-secondary);
}

.group-divider {
  height: 1px;
  background: var(--color-border);
  margin: 8px 16px;
}

/* 二级菜单项 - 增加左侧指示条 */
.sidebar-item.active {
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  border-left: 3px solid var(--color-primary);
  padding-left: 13px; /* 16px - 3px border */
}

/* 三级子菜单 - 展开收起动画 */
.submenu-items {
  overflow: hidden;
  max-height: 0;
  transition: max-height 0.25s ease;
}

.submenu-items.expanded {
  max-height: 200px;
}
```

### 3.2 分组折叠逻辑

```tsx
// 分组展开状态改为可交互
const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
  control: true,
  agent: true,
  settings: true,
})

const toggleGroup = (groupId: string) => {
  setExpandedGroups(prev => ({ ...prev, [groupId]: !prev[groupId] }))
}
```

### 3.3 折叠模式 tooltip

```tsx
// 折叠模式下菜单项添加 title 属性
{collapsed && <span className={styles['tooltip']}>{item.label}</span>}
```

### 3.4 全局布局变量新增

在 `global.css` 中添加：

```css
:root {
  --sidebar-width: 240px;
  --sidebar-collapsed-width: 60px;
  --color-border: rgba(0, 0, 0, 0.08);
  --color-primary-subtle: rgba(91, 141, 239, 0.08);
}

.dark {
  --color-border: rgba(255, 255, 255, 0.08);
  --color-primary-subtle: rgba(91, 141, 239, 0.12);
}
```

## 4. 实施步骤

1. 更新 `global.css` 添加新变量
2. 重构 `Sidebar.module.css` 样式
3. 更新 `Sidebar.tsx` 组件逻辑（分组折叠交互、tooltip、指示条）
4. 统一各页面布局 CSS（页头间距、最大宽度）

## 5. 验证标准

- TypeScript 编译无错误
- 三级菜单层级在视觉上可明确区分
- 折叠/展开模式正常工作
- 移动端响应式无异常
- 深色/浅色主题均正常
