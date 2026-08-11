# 现状功能与重复入口审计

## 1. 调研边界

本次以当前工作树中的实际源文件为准，重点检查：

- Web 路由：[frontend/src/router/index.tsx](../../../frontend/src/router/index.tsx)
- Web 外壳：[frontend/src/layouts/AppShell.tsx](../../../frontend/src/layouts/AppShell.tsx)
- Web 侧栏：[frontend/src/shared/components/Sidebar/Sidebar.tsx](../../../frontend/src/shared/components/Sidebar/Sidebar.tsx)
- Web 移动底栏：[frontend/src/shared/components/MobileTabBar/MobileTabBar.tsx](../../../frontend/src/shared/components/MobileTabBar/MobileTabBar.tsx)
- 桌面端原生菜单：[desktop/src/main/menu.ts](../../../desktop/src/main/menu.ts)
- 桌面端窗口：[desktop/src/main/window.ts](../../../desktop/src/main/window.ts)
- 桌面端托盘：[desktop/src/main/tray.ts](../../../desktop/src/main/tray.ts)
- Android 目的地：[android/Open-AwA-Android/app/src/main/java/com/xtys126/open_awa/core/nav/Destination.kt](../../../android/Open-AwA-Android/app/src/main/java/com/xtys126/open_awa/core/nav/Destination.kt)
- Android 外壳：[android/Open-AwA-Android/app/src/main/java/com/xtys126/open_awa/core/nav/AppShell.kt](../../../android/Open-AwA-Android/app/src/main/java/com/xtys126/open_awa/core/nav/AppShell.kt)
- Android 导航图：[android/Open-AwA-Android/app/src/main/java/com/xtys126/open_awa/core/nav/AppNavGraph.kt](../../../android/Open-AwA-Android/app/src/main/java/com/xtys126/open_awa/core/nav/AppNavGraph.kt)

本次只新增设计文件，不修改上述实现，也不触碰 `var/` 中的运行数据。

## 2. 三端现状

| 端 | 当前主导航 | 主要问题 |
|---|---|---|
| Web 大屏 | 可折叠侧栏，分为“控制台 / 智能体 / 设置”三组 | 约 22 个页面平铺；分组依据不一致；低频管理和高频任务同权重 |
| Web 小屏 | 聊天、记忆、技能、设置四个 Tab，加“更多”打开完整侧栏 | 底栏与抽屉仍是两套清单；靠 `mobileHidden` 人工去重；不是真正的信息架构收敛 |
| Electron 桌面 | 完整复用 Web 导航，另有系统菜单、托盘和全局快捷键 | 原生层与渲染层没有职责边界；菜单只有少数动作，无法形成桌面工作流 |
| Android 手机 | 顶栏汉堡菜单加长抽屉 | 手工复制 Web 目的地；所有页面近似同权；没有底栏、Rail 或平板双栏适配 |

## 3. 当前功能域

| 当前入口 | 实际职责 | 成熟度与观察 |
|---|---|---|
| 聊天 | 多轮对话、流式输出、会话历史、思考控制、子代理编排 | 核心高频能力，应成为默认入口 |
| 工作区 | 多项目工作区管理 | 是开发工作流的上下文，不应与编码、Vibe Coding 并列 |
| 编码 | 文件树、编辑器、搜索、终端、AI 对话、Git/Diff/LSP | 与工作区和 Vibe Coding 高度连续 |
| Vibe Coding | ACP Agent 会话、终端、文件预览、权限审批 | 应成为工作台中的 Agent 模式，而非独立产品区 |
| 仪表盘 | 系统资源、最近活动、业务数据 | 应并入“动态”的概览页 |
| 计费 | 用量、预算、价格、报表 | 属于动态中的用量，配置部分属于设置 |
| 收件箱 | 消息和通知聚合 | 属于动态中心 |
| 工作流 | 流程定义、条件分支、工具/技能/插件步骤 | 与定时任务和运行记录组成自动化闭环 |
| 定时任务 | AI 任务、插件命令、调度、执行历史 | 是自动化的一种触发方式，不是独立一级产品域 |
| 子智能体 | 子 Agent 配置、状态、资源限制 | 应作为自动化执行资源管理 |
| 讨论 | 多 Agent 任务讨论和状态 | 应挂在具体运行或任务详情内，不应是全局一级入口 |
| 技能 | 技能管理、启停、导入、执行 | 与插件共同构成“能力资源” |
| 技能市场 | 技能发现和安装 | 是技能页面的“发现”视图，不是独立页面 |
| 插件 | 安装、管理、权限、日志、热更新、回滚 | 当前 Web 已把“已安装 / 市场”合并为 Tab，应保留这一方向 |
| 角色 | 角色创建、编辑、选择 | 与角色市场共同构成“角色资源” |
| 角色市场 | 角色发现和安装 | 是角色页面的“发现”视图，不是独立页面 |
| 记忆 | 短期、长期、质量、检索、归档 | 与经验属于同一知识资源域 |
| 经验 | 经验文件浏览和编辑 | Android 记忆页已将经验作为 Tab，证明独立入口没有必要 |
| TTS | 语音合成、音色和克隆资源 | 作为资源库的“声音”，聊天中提供情境快捷入口 |
| 宠物 | 内置和自定义桌面宠物 | 属于外观与桌面伴侣设置，不属于智能体主任务 |
| IM 渠道 | 多渠道配置、状态、测试，包含微信 | 属于设置中的“连接”，不是消息消费入口 |
| 用户中心 | 个人信息、设备、画像、事实、洋葱画像 | 当前已经合并多个画像页面，应成为唯一账户入口 |
| 设置 | 通用、画像、模型/API、外观、搜索、提示词、计费、后端、高级配置 | 当前单页层级过深，需要重新分区，但不应进入五个主工作域 |

## 4. 已确认的重复与冲突

### 4.1 市场与管理重复

- `SkillsPage` 和 `SkillMarketPage` 被定义为两个页面；Android 的 `SkillsScreen` 却已经用“已安装 / 市场”两个 Tab 承载相同概念。
- `PluginsPage` 已经把市场整合为 Tab，但旧市场样式、文档入口和潜在旧路由仍保留。
- `RolesPage` 与 `RoleMarketPage` 继续并列。

结论：市场不是领域，只是资源列表的筛选状态。技能、插件、角色各保留一个规范页面。

### 4.2 开发工具重复

`/workspace`、`/coding`、`/vibe-coding` 都围绕同一项目上下文工作。当前分裂导致用户必须在不同页面重新理解项目、文件、终端和 Agent 会话的位置。

结论：合并为“工作台”，项目是一级上下文，编辑器和 Agent 是工作模式。

### 4.3 自动化重复

工作流定义、定时触发、子智能体执行、任务运行、讨论协作构成一个完整生命周期，却被拆成多个并列入口。

结论：合并为“自动化”，讨论只能出现在具体运行详情中。

### 4.4 知识重复

记忆页已经拥有短期、长期和质量 Tab，经验页又维护经验文件；Android 记忆页进一步把经验库纳入同一页面。

结论：合并为资源库中的“知识”，短期、长期、经验和质量成为子视图。

### 4.5 身份与配置重复

`/user` 已经包含个人信息和画像，`/user-profile` 仍独立存在；设置页又有画像设置。`/im` 是渠道配置，却被当作全局功能。

结论：个人数据进入“账户”，行为参数进入“设置 > AI 与个性”，渠道进入“设置 > 连接”。

## 5. Android 特有问题

Android 当前只有认证、聊天、通知、定时任务和 ACP 等少数路径拥有较完整 Repository。技能、工作流、角色、插件、记忆、TTS、设置等多个 Screen 仍包含未接入 Repository 的逻辑或模拟数据。正式导航把这些页面与核心功能并列，会制造“功能已完成”的错误预期。

新方案要求：

- 导航项必须同时满足路由存在、权限允许、平台实现达到发布门槛。
- 不允许以 `PlaceholderScreen` 替代正式功能入口。
- 尚未原生完成的能力可以从统一搜索中显示为“仅桌面/Web 可用”，但不能点击进入空页面。

## 6. 桌面端特有问题

Electron 目前加载完整 Web 前端，原生层主要负责窗口、托盘、通知、更新和少量快捷键。系统菜单与侧栏没有统一命令模型。

新方案要求：

- 原生菜单只呈现命令，不复制所有导航页面。
- 全局快捷键、托盘和命令面板调用同一组 `command_id`。
- 页面切换由统一导航清单驱动，窗口操作仍归 Electron 主进程。

