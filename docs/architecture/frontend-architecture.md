# 前端架构说明

本文档基于当前 `frontend/` 目录中的代码，对 Open-AwA 前端的页面结构、服务层组织和测试布局做说明。

## 1. 技术基础

前端使用：

- React 18
- TypeScript
- Vite
- React Router DOM
- Axios
- Zustand
- Recharts
- Vitest
- Playwright

参考：

- [package.json](file:///d:/代码/Open-AwA/frontend/package.json#L1-L38)

## 2. 入口与路由

前端应用入口：

- [main.tsx](file:///d:/代码/Open-AwA/frontend/src/main.tsx)
- [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L1-L91)

### 2.1 路由结构

当前前端已配置的路由页面包括：

- `/chat`
- `/dashboard`
- `/settings`
- `/skills`
- `/plugins`
- `/memory`
- `/billing`

参考：

- [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L70-L88)

## 3. 启动初始化逻辑

`App.tsx` 中的初始化流程会：

1. 从 `localStorage` 读取 token
2. 若 token 存在，调用 `/auth/me` 验证
3. 若 token 不存在或失效，尝试自动创建一个测试用户并登录
4. 初始化完成后再渲染主路由

参考：

- [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L20-L68)

这属于当前仓库的开发便利逻辑，应与正式生产登录方案区分。

## 4. 页面层

页面文件位于 `frontend/src/pages/`。

### 4.1 ChatPage

- 文件： [ChatPage.tsx](file:///d:/代码/Open-AwA/frontend/src/features/chat/ChatPage.tsx)
- 主要功能：聊天输入、消息展示、模型选择、输出模式切换（流式/直接）、保存默认模型
- 上下文机制：页面挂载或会话切换时自动从后端加载历史消息，支持多轮对话
- 流式性能优化：后台标签页时节流 DOM 更新，可见时 flush buffer
- 依赖：`chatAPI`、`chatStore`

### 4.2 DashboardPage

- 文件： [DashboardPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/DashboardPage.tsx#L1-L128)
- 主要功能：行为统计与计费趋势展示
- 依赖：`behaviorAPI`、`billingAPI`

### 4.3 SkillsPage

- 文件： [SkillsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/SkillsPage.tsx#L1-L104)
- 主要功能：技能列表、启用/禁用、卸载、打开创建技能弹窗

### 4.4 PluginsPage

- 文件： [PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/PluginsPage.tsx#L1-L260)
- 主要功能：
  - 展示插件列表
  - 导入 zip 插件
  - 启用/禁用
  - 查看权限状态
  - 授权与撤销权限
  - 打开调试面板

### 4.5 MemoryPage

- 文件： [MemoryPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/MemoryPage.tsx#L1-L154)
- 主要功能：短期记忆、长期记忆、经验记忆三个页签
- 其中经验记忆复用了 `ExperiencePage`

### 4.6 BillingPage

- 文件： [BillingPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/BillingPage.tsx#L1-L249)
- 主要功能：
  - 成本统计
  - 趋势图与饼图
  - 用量明细表
  - CSV 导出按钮

## 5. 组件层

组件位于 `frontend/src/components/`，当前较关键的有：

- [Sidebar.tsx](file:///d:/代码/Open-AwA/frontend/src/components/Sidebar.tsx)
- [SkillModal.tsx](file:///d:/代码/Open-AwA/frontend/src/components/SkillModal.tsx)
- [PluginDebugPanel.tsx](file:///d:/代码/Open-AwA/frontend/src/components/PluginDebugPanel.tsx)
- [ExperienceCard.tsx](file:///d:/代码/Open-AwA/frontend/src/components/ExperienceCard.tsx)
- [ExperienceModal.tsx](file:///d:/代码/Open-AwA/frontend/src/components/ExperienceModal.tsx)

其中 `PluginDebugPanel` 是插件页的重要调试入口，并且已经配有单元测试。

## 6. 服务层

服务层位于 `frontend/src/services/`。

### 6.1 通用 API 实例

- [api.ts](file:///d:/代码/Open-AwA/frontend/src/shared/api/api.ts)

当前特征：

- 通过 Axios 创建统一实例
- 默认 `baseURL` 为 `/api`
- 自动附加 Bearer Token 到请求头
- CSRF 双重提交 Cookie 保护
- 请求/响应拦截器

### 6.2 主要服务封装

#### 认证、聊天、技能、插件、记忆、提示词、会话、行为

集中定义在：

- [api.ts](file:///d:/代码/Open-AwA/frontend/src/shared/api/api.ts)

chatAPI 新增了 `getHistory` 方法，用于加载会话历史。
pluginsAPI 新增了 `discover` 和 `execute` 方法，分别用于发现可用插件和执行插件方法。

#### 计费服务

- [billingApi.ts](file:///d:/代码/Open-AwA/frontend/src/services/billingApi.ts#L1-L165)

#### 模型配置服务

- [modelsApi.ts](file:///d:/代码/Open-AwA/frontend/src/services/modelsApi.ts#L1-L115)

#### 经验服务

- [experiencesApi.ts](file:///d:/代码/Open-AwA/frontend/src/services/experiencesApi.ts)

## 7. 状态管理

当前仓库使用 Zustand，已明确可见的 store 为：

- [chatStore.ts](file:///d:/代码/Open-AwA/frontend/src/features/chat/store/chatStore.ts)

聊天页通过它管理：

- 消息列表
- 加载状态
- 会话 ID
- 输出模式（流式/直接）
- 全局模型选择
- 历史消息恢复（`setMessages`）
- 清空会话等操作

## 8. 类型定义

前端类型文件位于 `frontend/src/types/`，主要包括：

- [api.ts](file:///d:/代码/Open-AwA/frontend/src/types/api.ts)
- [dashboard.ts](file:///d:/代码/Open-AwA/frontend/src/types/dashboard.ts)
- [billing.ts](file:///d:/代码/Open-AwA/frontend/src/types/billing.ts)
- [plugin-sdk.d.ts](file:///d:/代码/Open-AwA/frontend/src/types/plugin-sdk.d.ts)

这些类型主要为页面、服务层和测试提供约束。

## 9. 样式组织

前端采用页面和组件局部 CSS 文件配合全局样式的方式。

可见结构包括：

- 页面级 CSS，如 `ChatPage.css`、`BillingPage.css`
- 组件级 CSS，如 `Sidebar.css`、`PluginDebugPanel.css`
- 全局样式： [global.css](file:///d:/代码/Open-AwA/frontend/src/styles/global.css)

## 10. 测试结构

### 10.1 单元测试

位于：

- `frontend/src/__tests__/`

当前已可见测试包括：

- [ChatPage.test.tsx](file:///d:/代码/Open-AwA/frontend/src/__tests__/ChatPage.test.tsx)
- [PluginDebugPanel.test.tsx](file:///d:/代码/Open-AwA/frontend/src/__tests__/PluginDebugPanel.test.tsx)
- [PluginsPage.test.tsx](file:///d:/代码/Open-AwA/frontend/src/__tests__/PluginsPage.test.tsx#L1-L130)
- [pluginTypes.test.ts](file:///d:/代码/Open-AwA/frontend/src/__tests__/pluginTypes.test.ts)

### 10.2 E2E 测试

位于：

- `frontend/tests/e2e/`

配置文件：

- [playwright.config.ts](file:///d:/代码/Open-AwA/frontend/playwright.config.ts#L1-L54)

该配置会在测试时自动启动：

- 后端 `uvicorn main:app`
- 前端 `npm run dev`

## 11. 前端与后端的交互方式

大致流向如下：

```text
用户操作页面
  -> 页面调用 services 中的方法
  -> Axios 请求 `/api/...`
  -> 后端返回 JSON
  -> 页面更新本地 state 或 Zustand store
  -> 组件重渲染
```

以插件权限为例，可追踪：

- [PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/PluginsPage.tsx#L34-L98)
- [api.ts](file:///d:/代码/Open-AwA/frontend/src/services/api.ts#L125-L133)

## 12. 当前前端架构特点

从当前代码看，前端具有以下特点：

- 页面路由清晰，功能页划分明确
- API 封装较集中，便于联调
- 聊天、插件、计费、记忆等模块分离度较高
- 仍保留一些开发期便捷逻辑，例如自动创建测试用户
- 有单测和 E2E 测试基础，但整体仍处于持续演进状态

## 13. 建议阅读顺序

如果你要继续维护前端，建议按如下顺序：

1. [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L1-L91)
2. [api.ts](file:///d:/代码/Open-AwA/frontend/src/services/api.ts#L1-L216)
3. 各页面文件
4. 相关组件与 CSS
5. `src/__tests__/` 和 `tests/e2e/`
