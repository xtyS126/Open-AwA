# Open-AwA 未来规划路线图

> 本文档基于项目当前实现状态，制定各功能模块的演进计划。
> 最后更新: 2026-04-11

---

## 目录

1. [MCP 协议支持](#1-mcp-协议支持)
2. [插件市场](#2-插件市场)
3. [Chain-of-Thought 改进](#3-chain-of-thought-改进)
4. [多语言模型支持扩展](#4-多语言模型支持扩展)
5. [安全增强](#5-安全增强)
6. [微信集成完善](#6-微信集成完善)
7. [前端 UI 改进](#7-前端-ui-改进)

---

## 1. MCP 协议支持

### 1.1 当前状态

- 完成度: **0%**
- 系统尚未支持 Model Context Protocol 标准
- 当前通过 Skill 系统承载部分工具调用能力

### 1.2 目标

实现 MCP 协议的客户端支持，使 Open-AwA 能够连接外部 MCP Server，发现并调用其提供的工具（Tools）和资源（Resources），实现标准化的工具集成生态。

### 1.3 实现计划

#### 1.3.1 MCP 客户端核心 (`backend/mcp/`)

- `client.py` - MCP 客户端实现，管理与 MCP Server 的连接
- `protocol.py` - MCP 协议消息定义（JSON-RPC 2.0 格式）
- `transport.py` - 传输层，支持 stdio 和 SSE 两种连接方式
- `tool_discovery.py` - 工具发现，解析 Server 暴露的 tools/list
- `types.py` - MCP 类型定义（Tool, Resource, Prompt 等）

#### 1.3.2 MCP 服务器配置管理

- `config.py` - MCP Server 配置管理（name, command, args, env）
- 数据库表 `mcp_servers` 存储已配置的 MCP Server 信息
- 支持 JSON 配置文件导入（兼容 Claude Desktop 格式）

#### 1.3.3 集成到 Agent 主流程

- Executor 层增加 MCP 工具调用能力
- Planner 层在规划时可选择 MCP 工具
- 工具列表聚合 Skill + MCP Tools

#### 1.3.4 API 路由 (`backend/api/routes/mcp.py`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/mcp/servers | 获取已配置的 MCP Server 列表 |
| POST | /api/mcp/servers | 添加 MCP Server 配置 |
| DELETE | /api/mcp/servers/{id} | 删除 MCP Server 配置 |
| POST | /api/mcp/servers/{id}/connect | 连接指定 Server |
| POST | /api/mcp/servers/{id}/disconnect | 断开连接 |
| GET | /api/mcp/servers/{id}/tools | 获取 Server 暴露的工具列表 |
| POST | /api/mcp/tools/call | 调用 MCP 工具 |

#### 1.3.5 前端页面

- Settings 页面新增 MCP Server 配置面板
- 展示已配置 Server 的连接状态和工具列表
- 支持 JSON 配置导入

### 1.4 验收标准

- [ ] 能通过 stdio 连接本地 MCP Server
- [ ] 能通过 SSE 连接远程 MCP Server
- [ ] 工具发现正确解析 tools/list 响应
- [ ] 工具调用正确传递参数和返回结果
- [ ] Agent 主流程可自动选择并调用 MCP 工具
- [ ] 前端可配置/管理 MCP Server
- [ ] 连接异常时有超时和重连机制

---

## 2. 插件市场

### 2.1 当前状态

- 完成度: **30%**
- 前端"浏览插件市场"按钮已存在，但未连接逻辑
- 后端已有插件安装/卸载/启用/禁用接口
- 已有下载域名白名单和大小限制

### 2.2 目标

实现插件市场的浏览、搜索、安装功能，使用户可以从集中式插件仓库发现和安装社区插件。

### 2.3 实现计划

#### 2.3.1 后端插件市场服务 (`backend/plugins/marketplace/`)

- `registry.py` - 插件注册表，管理可用插件元数据
- `search.py` - 搜索与筛选逻辑（名称、分类、标签）
- 数据库表 `marketplace_plugins` 存储插件元数据

#### 2.3.2 API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/marketplace/plugins | 浏览插件列表（分页、分类） |
| GET | /api/marketplace/plugins/search | 搜索插件 |
| GET | /api/marketplace/plugins/{id} | 获取插件详情 |
| POST | /api/marketplace/plugins/{id}/install | 从市场安装插件 |
| GET | /api/marketplace/categories | 获取分类列表 |

#### 2.3.3 前端插件市场页面

- `MarketplacePage.tsx` - 市场主页面
- 插件卡片展示（图标、名称、描述、作者、版本）
- 搜索栏和分类筛选器
- 一键安装按钮
- 连接 PluginsPage 的"浏览插件市场"按钮

#### 2.3.4 内置插件种子数据

- 将现有三个示例插件（hello-world, theme-switcher, data-chart）注册为市场种子数据

### 2.4 验收标准

- [ ] 市场页面可正常加载，展示可用插件列表
- [ ] 搜索功能按名称/描述匹配
- [ ] 分类筛选器工作正常
- [ ] 可从市场一键安装插件
- [ ] PluginsPage "浏览插件市场"按钮跳转到市场页面
- [ ] 内置示例插件在市场中可见

---

## 3. Chain-of-Thought 改进

### 3.1 当前状态

- 完成度: **70%**
- 前端 ReasoningContent.tsx 已实现折叠/展开、流式跟踪、localStorage 持久化
- 缺少后端推理内容的结构化传输和模型层适配

### 3.2 目标

完善 Chain-of-Thought 的端到端链路，使模型的思维过程能完整传输和展示，并支持思维深度配置。

### 3.3 实现计划

#### 3.3.1 后端模型层适配 (`backend/core/model_service.py`)

- 识别并解析模型返回的 reasoning/thinking 字段
- OpenAI o1/o3 系列: 解析 `reasoning_content` 字段
- Anthropic Claude: 解析 `thinking` content block
- DeepSeek: 解析 `reasoning_content` 字段
- 通过 SSE/WebSocket 分段传输推理内容（type: "reasoning"）

#### 3.3.2 推理参数配置

- 聊天接口增加 `reasoning_effort` 参数（high/medium/low）
- 设置页面支持默认推理深度配置
- Token 统计区分 reasoning tokens 和 output tokens

#### 3.3.3 前端展示增强

- ReasoningContent 组件展示 token 消耗
- 推理耗时统计展示
- 支持复制推理内容

### 3.4 验收标准

- [ ] 支持 OpenAI/Anthropic/DeepSeek 的推理内容解析
- [ ] SSE 流式传输包含 reasoning 类型消息
- [ ] 前端正确展示推理过程内容
- [ ] reasoning_effort 参数可配置并生效
- [ ] Token 统计区分推理和输出

---

## 4. 多语言模型支持扩展

### 4.1 当前状态

- 完成度: **90%**
- 已支持: OpenAI, Anthropic, DeepSeek
- 协议适配层按 provider 构造不同请求

### 4.2 目标

扩展支持更多模型提供商，并增加本地/开源模型支持框架。

### 4.3 实现计划

#### 4.3.1 新增模型提供商

- 通义千问 (Qwen): 兼容 OpenAI 格式，配置 base_url
- 智谱 AI (GLM): 需适配其 API 签名方式
- Kimi (Moonshot): 兼容 OpenAI 格式

#### 4.3.2 本地模型支持

- Ollama 集成: 使用 OpenAI 兼容接口连接本地 Ollama
- 配置项增加 `OLLAMA_BASE_URL`（默认 http://localhost:11434）
- 模型列表自动发现（调用 Ollama /api/tags）

#### 4.3.3 模型能力探测

- `capabilities` 字段标识模型支持的能力（vision, function_calling, reasoning）
- 前端根据能力动态显示/隐藏功能入口

### 4.4 验收标准

- [ ] 通义千问/Kimi 模型可正常对话
- [ ] Ollama 本地模型可连接和调用
- [ ] 模型列表自动发现 Ollama 可用模型
- [ ] 模型能力标识正确

---

## 5. 安全增强

### 5.1 当前状态

- 完成度: **75%**
- 三层权限控制已实现（auto_approve/user_confirm/admin_only）
- 审计日志异步记录已实现
- 沙箱隔离有命令白名单和路径校验

### 5.2 目标

完善安全体系，增加 RBAC 权限模型、审计日志前端展示、资源限制执行。

### 5.3 实现计划

#### 5.3.1 RBAC 权限模型

- 数据库表: `roles`, `role_permissions`, `user_roles`
- 内置角色: admin, developer, viewer
- 权限粒度: 模块级 + 操作级（如 `plugin:install`, `skill:execute`）

#### 5.3.2 审计日志前端

- Settings 页面新增"安全审计"标签页
- 审计日志列表（时间、用户、操作、资源、结果）
- 筛选器（时间范围、用户、操作类型）
- 导出功能

#### 5.3.3 资源限制

- 沙箱执行超时控制（默认 30s）
- 内存使用限制
- 文件操作大小限制
- 网络请求速率限制

### 5.4 验收标准

- [ ] RBAC 角色可分配，权限校验生效
- [ ] 审计日志页面可查看和筛选
- [ ] 沙箱超时控制生效
- [ ] 资源限制参数可配置

---

## 6. 微信集成完善

### 6.1 当前状态

- 完成度: **80%**
- Skill 适配层已完成，二维码登录流程已实现
- 通讯页面独立入口已存在
- 已知问题: 绑定状态仅在内存中，硬编码参数

### 6.2 目标

完善微信集成的稳定性和状态管理，确保绑定状态持久化。

### 6.3 实现计划

#### 6.3.1 绑定状态持久化

- 数据库表 `weixin_bindings` 存储绑定关系
- 字段: user_id, weixin_account_id, token, binding_status, created_at, updated_at
- 登录成功后自动持久化绑定信息

#### 6.3.2 会话管理改进

- Session 过期自动刷新 token
- 断线重连机制
- 绑定失败独立错误处理

#### 6.3.3 硬编码参数配置化

- 将 bot_type, channel_version 等提取到配置文件
- 前端设置页面可修改微信集成参数

### 6.4 验收标准

- [ ] 绑定状态重启后仍保留
- [ ] 会话过期时自动恢复
- [ ] 硬编码参数全部提取到配置
- [ ] 绑定失败时前端展示明确错误

---

## 7. 前端 UI 改进

### 7.1 当前状态

- 完成度: **85%**
- 设计令牌系统完整（CSS 变量）
- 深色/浅色主题切换已实现
- CSS Modules 模式统一

### 7.2 目标

进一步提升 UI 一致性和用户体验，实现响应式设计和组件文档化。

### 7.3 实现计划

#### 7.3.1 响应式设计

- 移动端适配（断点: 768px, 1024px）
- Sidebar 移动端折叠为汉堡菜单
- 表格/图表自适应宽度

#### 7.3.2 UI 一致性提升

- 统一按钮样式（primary, secondary, danger, ghost）
- 统一表单控件样式
- 统一卡片/面板组件
- 统一 Loading 状态和空状态展示

#### 7.3.3 交互体验优化

- 页面切换动画（fade/slide）
- Toast 通知组件
- 确认对话框组件
- 键盘快捷键支持

### 7.4 验收标准

- [ ] 768px 断点下 Sidebar 折叠
- [ ] 按钮/表单样式统一
- [ ] Toast 通知替代 alert
- [ ] Loading/Empty 状态统一

---

## 实施优先级

| 优先级 | 模块 | 理由 |
|--------|------|------|
| P0 | MCP 协议支持 | 平台核心能力，工具生态扩展基础 |
| P0 | 安全增强 | 生产环境部署前置条件 |
| P1 | 插件市场 | 社区生态建设，UI 基础已就位 |
| P1 | Chain-of-Thought | 用户体验关键特性 |
| P2 | 微信集成完善 | 已有特定用户群，需稳定性保障 |
| P2 | 多语言模型扩展 | 当前已可用，按需扩展 |
| P3 | 前端 UI 改进 | 持续优化项 |
