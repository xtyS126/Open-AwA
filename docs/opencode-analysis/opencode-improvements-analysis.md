# OpenCode 优秀实践分析与 Open-AwA 改进建议

> 分析日期：2026-06-07
> 分析对象：https://github.com/anomalyco/opencode (dev 分支)
> 分析目的：深度研究 OpenCode 架构中可用于改进 Open-AwA 的设计模式与技术实现

---

## 目录

1. [OpenCode 项目概览](#1-opencode-项目概览)
2. [核心架构差异分析](#2-核心架构差异分析)
3. [一、Agent 权限与身份系统](#3-agent-权限与身份系统)
4. [二、结构化上下文压缩系统](#4-结构化上下文压缩系统)
5. [三、工具注册中心架构](#5-工具注册中心架构)
6. [四、技能系统增强](#6-技能系统增强)
7. [五、事件溯源会话架构](#7-事件溯源会话架构)
8. [六、插件 Hook 系统](#8-插件-hook-系统)
9. [七、AI 驱动命令系统](#9-ai-驱动命令系统)
10. [八、配置分层系统](#10-配置分层系统)
11. [九、终端 UI 设计模式](#11-终端-ui-设计模式)
12. [十、CI/CD 与质量基础设施](#12-cicd-与质量基础设施)
13. [改进优先级与实施路径](#13-改进优先级与实施路径)

---

## 1. OpenCode 项目概览

### 1.1 项目定位

OpenCode 是一个开源的 AI 编码代理（AI Coding Agent），由 anomalyco 团队开发。它提供终端 TUI、桌面应用和 Web 界面三种交互方式，核心定位为"终端中的 AI 编程助手"。

### 1.2 技术栈

| 层面 | OpenCode | Open-AwA |
|------|----------|----------|
| **语言** | TypeScript (Bun runtime) | Python 3.11+ (后端) + TypeScript/React (前端) |
| **函数式核心** | Effect.ts (Effect System) | 传统 async/await |
| **前端框架** | SolidJS + @opentui | React 18 + Zustand |
| **数据库** | Drizzle ORM + SQLite | SQLAlchemy + SQLite |
| **LLM SDK** | @ai-sdk (Vercel AI SDK) | LiteLLM + httpx |
| **包管理** | Bun workspaces (monorepo) | pip + npm (分离仓库) |
| **类型系统** | TypeScript 5.8 + Schema (Effect/Schema) | Pydantic v2 |
| **测试** | Vitest + Playwright | pytest + Vitest + Playwright |
| **CLI 框架** | yargs | 无独立 CLI（仅 Web） |

### 1.3 Monorepo 包结构

```
packages/
├── core/          # 核心引擎：Agent, Session, Tool, Permission, Plugin, Skill, Config
├── opencode/      # CLI + TUI + 命令系统入口
├── llm/           # LLM 抽象层（基于 @ai-sdk）
├── function/      # 函数/工具定义 API
├── plugin/        # 插件系统接口
├── ui/            # SolidJS 共享 UI 组件
├── app/           # Web 应用（SolidJS Start）
├── desktop/       # Electron 桌面应用
├── console/       # 管理控制台
├── server/        # 后端服务（Hono）
├── sdk/           # 外部 SDK
├── slack/         # Slack 集成
├── identity/      # 认证服务
├── docs/          # 文档
├── web/           # 静态站点
└── ...
```

### 1.4 V2 架构服务边界

OpenCode 正在从 V1 迁移到 V2 架构，V2 采用 Effect.ts 的服务层模式：

```
AgentV2.Service    → 代理管理与选择
SessionV2.Service  → 会话生命周期（CRUD、消息、事件流）
ToolRegistry       → 工具注册、定义解析、执行与结算
PermissionV2       → 权限请求、断言与决策记忆
PluginV2.Service   → 插件加载、Hook 触发
SkillV2.Service    → 技能发现、加载与过滤
Config.Service     → 分层配置管理
Location.Service   → 工作目录上下文
```

---

## 2. 核心架构差异分析

### 2.1 运行时模型

| 维度 | OpenCode | Open-AwA | 影响 |
|------|----------|----------|------|
| **依赖注入** | Effect.ts Context + Layer | FastAPI Depends() | OpenCode 的 DI 更细粒度，支持作用域生命周期 |
| **错误处理** | Effect 类型化错误（Schema.TaggedErrorClass） | Python Exception + HTTPException | OpenCode 错误类型更精确，编译时检查 |
| **并发模型** | Effect Fiber（轻量级绿色线程） | asyncio Task | Effect Fiber 支持更好的取消和结构化并发 |
| **状态管理** | Immer（不可变草稿） | SQLAlchemy ORM + 内存状态 | OpenCode 状态修改更安全，支持撤销 |
| **事件系统** | EventV2（类型化事件 + 聚合） | 隐式（通过 ORM 变更） | OpenCode 事件驱动更明确，支持审计 |

### 2.2 Open-AwA 当前 agent 执行流程

```
comprehension.py → planner.py → executor.py → feedback.py
```

当前流程是线性的，工具调用内嵌在 executor 中，权限检查通过 RBAC 统一检查。

### 2.3 OpenCode 的 agent 执行流程

```
SessionRunner.run()
  └─ runTurn()
       ├─ 加载 SystemContext（系统提示 + 技能指导）
       ├─ 构建 LLM 请求（含工具定义）
       ├─ 上下文溢出检测 → 自动压缩
       ├─ llm.stream(request)
       │   ├─ text-delta → 发布事件
       │   ├─ tool-call → ToolRegistry.settle()
       │   │   ├─ 权限断言（PermissionV2.assert）
       │   │   ├─ 工具执行
       │   │   └─ 发布工具结果事件
       │   └─ provider-error → 处理
       └─ 工具执行后继续循环（最多 25 步）
```

---

## 3. Agent 权限与身份系统

### 3.1 OpenCode 设计

**核心概念：**

```typescript
// 权限规则
Rule = { action: string, resource: string, effect: "allow" | "deny" | "ask" }

// 代理信息
Agent.Info = {
  id: ID,
  model: ModelRef,
  system: string,          // 自定义系统提示
  description: string,
  mode: "subagent" | "primary" | "all",
  hidden: boolean,
  color: Color,
  steps: number,           // 最大工具调用步数
  permissions: Rule[]      // 代理专属权限规则
}
```

**关键特性：**

1. **多代理切换** — 用户可以通过 Tab 键在 build（全权限）和 plan（只读）代理间切换
2. **通配符权限匹配** — `Wildcard.match(action, rule.action)` 支持 `*` 和 `skill:*` 模式
3. **权限决策记忆** — 用户可以选择 `once`（本次）、`always`（持久化）、`reject`（拒绝）
4. **代理级别权限隔离** — 每个代理有独立的 permissions 规则，子代理继承受限权限
5. **权限评估优先级** — deny > ask > allow，越具体的规则优先级越高

**权限检查流程：**

```
1. 工具调用 → PermissionV2.assert({sessionID, action, resources, agent})
2. 评估：查找匹配的 Rule（先代理规则，再全局规则，再已保存规则）
3. 如果是 allow → 执行
4. 如果是 deny → 抛出 DeniedError（含相关规则）
5. 如果是 ask → 创建 Pending 请求 → 阻塞等待用户回复
6. 用户回复 always 且含 save 资源 → 持久化到 PermissionSaved
7. 用户回复 always → 级联批准同 session 的其他 pending 请求
```

### 3.2 Open-AwA 当前实现

- RBAC 基于角色的权限控制
- 通配符匹配已有实现（`check_permission` 支持 `skill:*` 匹配）
- 但缺少**代理级别**的权限区分
- 缺少**运行时权限请求**机制（ask 模式）
- 缺少**权限决策记忆**（always 持久化）

### 3.3 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P0** | 代理级别权限规则 | 为不同代理（如 build/plan）定义独立的 permissions |
| **P0** | 运行时权限请求 | 工具执行前支持 ask 模式，用户可选择 allow/deny/always |
| **P1** | 权限决策持久化 | PermissionSaved 表存储用户批准的权限，跨会话生效 |
| **P1** | 拒绝时反馈原因 | CorrectedError 携带反馈信息，agent 可据此调整行为 |
| **P2** | 代理模式定义 | primary（主代理）/ subagent（子代理）/ all（通用）模式 |

---

## 4. 结构化上下文压缩系统

### 4.1 OpenCode 设计

**核心机制：**

```
Compaction 触发条件：
  当前上下文 token 数 > (模型上下文窗口 - max(输出 token, 缓冲 token))
  → 自动触发压缩

压缩流程：
  1. select() → 按 token 预算保留最近消息
  2. 被截断部分 → 生成结构化摘要
  3. 摘要模板（SUMMARY_TEMPLATE）：
     - Goal（目标）
     - Constraints & Preferences（约束与偏好）
     - Progress（进度：Done/In Progress/Blocked）
     - Key Decisions（关键决策）
     - Next Steps（下一步）
     - Critical Context（关键上下文：错误/问题）
     - Relevant Files（相关文件及原因）
  4. 新摘要替换历史 → 继续对话
```

**摘要模板设计原则：**
- 每个部分都必须保留（即使为空写 `(none)`）
- 使用简洁的项目符号而非段落
- 保留精确的文件路径、命令、错误字符串
- 不提及摘要过程本身

**关键参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `buffer` | 20,000 tokens | 安全缓冲区 |
| `keep.tokens` | 8,000 tokens | 保留最近消息的 token 数 |
| `auto` | true | 是否自动压缩 |
| `summary_output_tokens` | 4,096 | 摘要生成的最大 token 数 |

### 4.2 Open-AwA 当前实现

- ShortTermMemory 存储会话历史
- 没有自动上下文压缩
- 长对话可能导致上下文溢出

### 4.3 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P0** | 自动上下文溢出检测 | 基于 token 估算检测是否需要压缩 |
| **P0** | 结构化摘要模板 | 采用 OpenCode 的 7 段式摘要模板 |
| **P1** | 可配置压缩参数 | buffer/tokens/auto 通过配置控制 |
| **P1** | 增量摘要合并 | 新摘要与旧摘要合并而非重新生成 |
| **P2** | 压缩事件日志 | 记录压缩历史用于审计和调试 |

---

## 5. 工具注册中心架构

### 5.1 OpenCode 设计

**三层工具系统：**

```
┌─────────────────────────────────────────────┐
│               ToolRegistry                   │
│  ┌───────────────────────────────────────┐  │
│  │  Location Tools (Built-in)            │  │
│  │  bash, read, write, edit, glob, grep, │  │
│  │  web_fetch, web_search, skill,        │  │
│  │  question, todo_write, apply_patch    │  │
│  │  ★ 最高优先级，覆盖应用工具           │  │
│  └───────────────────────────────────────┘  │
│  ┌───────────────────────────────────────┐  │
│  │  Application Tools (Dynamic)          │  │
│  │  MCP tools, plugin-contributed tools  │  │
│  │  ★ 低优先级，Location tools 优先      │  │
│  └───────────────────────────────────────┘  │
│  ┌───────────────────────────────────────┐  │
│  │  Tool Output Store                    │  │
│  │  输出截断、持久化、路径跟踪           │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

**工具定义模式：**

```typescript
// 声明式工具定义
const definition = Tool.make({
  description: "工具描述",
  parameters: Schema.Struct({...}),  // Effect/Schema 定义
  success: Schema.Struct({...}),     // 成功输出类型
  toModelOutput: ({output}) => [...], // 转换为 LLM 可理解的格式
})

// 注册到 Registry
registry.contribute((editor) =>
  editor.set(name, {
    tool: definition,
    permission: { action: "bash", resource: "*" },
    authorize: (input) => Effect.gen(...),  // 权限检查
    execute: (input) => Effect.gen(...),    // 实际执行
    outputPaths: (output) => [...],         // 输出文件路径
  })
)
```

**关键设计决策：**

1. **Location 作用域** — ToolRegistry 是 Location 级别的（每个工作目录一个实例），而非全局单例
2. **应用工具共享** — ApplicationTools 是进程级别共享的，跨 Location 生效
3. **贡献/撤销机制** — 通过 Scope 管理，Scope 关闭时自动清理贡献
4. **动态移除语义** — 工具移除时不阻塞正在进行的调用（无租约/快照）
5. **权限检查内置** — 每个工具执行入口都有 `assertPermission` 调用点

### 5.2 Open-AwA 当前实现

- 工具定义分散在 `executor.py` 中
- 权限检查通过 RBAC `check_permission` 统一处理
- 缺少工具注册中心的概念
- MCP 工具通过 `mcp_{server_id}/{tool_name}` 模式分发

### 5.3 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P0** | 统一工具注册表 | ToolRegistry 类管理所有工具的定义/优先级/执行 |
| **P1** | 声明式工具定义 | 类似 Tool.make() 的参数/成功/执行三要素模式 |
| **P1** | 工具输出存储 | ToolOutputStore 处理截断和持久化 |
| **P2** | 动态工具贡献 | 支持 Scope 级别的工具注册与撤销 |
| **P2** | 工具优先级系统 | Location tools > Application tools 的优先级链 |

---

## 6. 技能系统增强

### 6.1 OpenCode 设计

**多源技能发现：**

```typescript
SkillSource = 
  | { type: "directory", path: AbsolutePath }   // 本地目录
  | { type: "url", url: string }                // 远程 URL（Git 仓库）
  | { type: "embedded", skill: Info }           // 内嵌技能
```

**技能定义格式（Markdown + Frontmatter）：**

```markdown
---
name: my-skill
description: 技能描述
slash: true    # 是否作为斜杠命令
---

技能内容（Markdown 格式的系统提示）
```

**技能过滤：**

```typescript
// 根据代理权限过滤可用技能
available(skills, agent) = 
  skills.filter(skill => 
    evaluate("skill", skill.name, agent.permissions).effect !== "deny"
  )
```

**技能指导生成：**

`SkillGuidance` 服务将所有可用技能编译为 agent 的系统提示的一部分，格式为：

```
## Available Skills

- my-skill: 技能描述
- another-skill: 另一个技能描述
```

### 6.2 Open-AwA 当前实现

- Skill 系统已有：`skill_engine.py`、`skill_executor.py`、`skill_registry.py`、`skill_loader.py`
- Skill 注册和加载已有基础
- 缺少多源发现（仅本地目录）
- 缺少代理权限过滤
- 缺少技能指导注入

### 6.3 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P1** | 远程技能源 | 支持 URL/Git 仓库作为技能来源 |
| **P1** | 技能权限过滤 | 根据代理权限隐藏不可用技能 |
| **P2** | 技能指导注入 | 自动将可用技能列表注入系统提示 |
| **P2** | Markdown 技能格式 | 统一使用 Markdown + Frontmatter 定义技能 |

---

## 7. 事件溯源会话架构

### 7.1 OpenCode 设计

**核心概念：**

```
事件流：UserPrompted → StepStarted → TextDelta* → ToolCall → ToolResult → StepFinished
聚合：SessionProjector 将事件投影为 SessionInfo 视图
消息：SessionMessage 是事件的投影结果，存储在 SQLite 中
```

**事件类型（SessionEvent）：**
- `UserPrompted` / `ShellCommand` / `SkillInvoked`
- `StepStarted` / `StepFinished` / `StepFailed`
- `TextDelta` / `ReasoningDelta` / `ToolCall` / `ToolResult`
- `CompactionStarted` / `CompactionEnded`
- `ModelSwitched` / `AgentSwitched`
- `TitleChanged` / `InterruptRequested`

**投影器（SessionProjector）：**

```typescript
SessionProjector 订阅事件流，将每个事件投影为：
  1. SessionInfo 更新（标题、token 消耗、费用）
  2. SessionMessage 追加（user/assistant/system/shell/compaction）
  3. Todo 状态更新
```

**优势：**
- 完整审计跟踪（每个操作都有事件记录）
- 支持时间旅行（重放事件得到任意时刻状态）
- 解耦写入和读取（CQRS 风格）
- 松耦合的消费者（多个投影器独立工作）

### 7.2 Open-AwA 当前实现

- 会话消息直接写入数据库（无事件层）
- ShortTermMemory 管理对话历史
- 无事件溯源概念

### 7.3 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P2** | 关键操作事件日志 | 先为核心操作增加事件记录（不改变存储模型） |
| **P2** | 会话审计视图 | 基于事件日志提供审计查询 |
| **P3** | 事件投影器 | 异步投影器更新聚合视图 |
| **P3** | 事件重放 | 支持从事件流重建会话状态 |

---

## 8. 插件 Hook 系统

### 8.1 OpenCode 设计

**Hook 定义：**

```typescript
type HookSpec = {
  "catalog.transform": {
    input: Catalog.Editor      // 文件目录编辑器
    output: {}
  }
  "account.switched": {
    input: { serviceID, from?, to? }
    output: {}
  }
  "aisdk.language": {
    input: { model, sdk, options }
    output: { language?: LanguageModelV3 }
  }
  "aisdk.sdk": {
    input: { model, package, options }
    output: { sdk?: any }
  }
}
```

**关键设计：**
- 每个 Hook 有类型化的输入和输出
- Hook 函数接收 `Draft<T>`（Immer 草稿），可安全修改输出
- 插件在独立的 Effect Scope 中运行
- 错误隔离：单个插件失败不影响其他插件
- 支持 `triggerFor(id, name, input, output)` 针对特定插件触发

### 8.2 Open-AwA 当前实现

- 插件系统已有：PluginManager、生命周期状态机、沙箱执行
- 蓝绿热更新
- 但缺少类型化的 Hook 系统
- 插件通过类继承和重写方法扩展

### 8.3 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P1** | 类型化 Hook 接口 | 定义 HookSpec，每个 Hook 有明确的输入/输出类型 |
| **P1** | Hook 隔离执行 | 每个 Hook 在独立作用域中运行，错误不传播 |
| **P2** | Immer 风格草稿 | Hook 接收可修改的草稿对象而非不可变引用 |
| **P2** | 插件 Hook 注册 | 插件通过 `define({id, effect})` 注册 Hook |

---

## 9. AI 驱动命令系统

### 9.1 OpenCode 设计

**命令定义（.opencode/command/*.md）：**

```markdown
---
description: git commit and push
model: opencode/kimi-k2.5    # 指定模型
subtask: true                 # 是否子任务
---

commit and push

make sure it includes a prefix like docs:/tui:/core:/ci:

## GIT DIFF
!`git diff`

## GIT STATUS --short
!`git status --short`
```

**关键特性：**
- 命令通过 Markdown 文件定义，支持 Frontmatter 元数据
- `!command` 语法用于注入 shell 命令输出
- 支持指定模型、subtask 模式
- 命令可以链式调用（一个命令的输出作为下一个的输入）

**内建命令列表：**
- `commit` — 生成 commit message 并提交
- `changelog` — 生成变更日志
- `issues` — 管理 GitHub Issues
- `learn` — 学习代码库知识
- `rmslop` — 清理代码
- `spellcheck` — 拼写检查
- `translate` — 翻译
- `ai-deps` — AI 依赖分析

### 9.2 Open-AwA 当前实现

- 无 AI 驱动命令系统
- Skill 系统可以部分实现类似功能
- 无 Markdown 定义的命令模板

### 9.3 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P2** | Markdown 命令定义 | 支持通过 .md 文件定义 AI 命令 |
| **P2** | Shell 注入语法 | `!command` 语法在命令执行前注入 shell 输出 |
| **P2** | 命令模型指定 | 允许命令指定使用的 LLM 模型 |
| **P3** | 子任务模式 | 命令可以作为子代理运行 |

---

## 10. 配置分层系统

### 10.1 OpenCode 设计

**配置优先级（从低到高）：**

```
1. 默认值（硬编码）
2. 全局配置（~/.opencode/config.jsonc）
3. 项目配置（.opencode/config.jsonc）
4. 环境变量
5. CLI 参数
```

**配置结构：**

```typescript
Config.Info = {
  $schema: string,           // JSON Schema 引用
  shell: string,             // 默认 shell
  model: string,             // 默认模型
  default_agent: string,     // 默认代理
  autoupdate: boolean | "notify",
  share: "manual" | "auto" | "disabled",
  username: string,
  permissions: Rule[],       // 全局权限规则
  agents: Record<string, Agent>,  // 代理定义（可覆盖内建代理）
  snapshots: boolean,        // 快照功能
  watcher: {...},            // 文件监控
  formatter: {...},          // 代码格式化
  lsp: {...},                // 语言服务器
  attachments: {...},        // 附件处理
  tool_output: {...},        // 工具输出截断
  mcp: {...},                // MCP 服务器
  compaction: {...},         // 压缩设置
  skills: string[],          // 额外技能路径
  commands: Record<string, Command>,  // 命令定义
  instructions: string[],    // 额外指令路径
  references: {...},         // 外部引用
  plugins: string[],         // 插件列表
  experimental: {...},       // 实验性功能
}
```

**Markdown 嵌入式配置：**

OpenCode 支持在 Markdown 文件的 Frontmatter 中嵌入配置，通过 `ConfigMarkdown.parseOption()` 解析。这允许在 CLAUDE.md、AGENTS.md 等文件中内联项目配置。

### 10.2 Open-AwA 当前实现

- 配置通过 `.env` 文件和代码中的 `Settings` 类管理
- 无分层配置（全局/项目/环境变量优先级链）
- 无 Markdown 嵌入式配置

### 10.3 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P1** | 分层配置系统 | 全局 → 项目 → 环境变量 优先级链 |
| **P2** | JSON Schema 验证 | 配置文件 schema 自动补全和验证 |
| **P2** | Markdown 配置嵌入 | 在 CLAUDE.md/AGENTS.md 中解析配置项 |
| **P3** | 配置热加载 | 文件变更时自动重载配置 |

---

## 11. 终端 UI 设计模式

### 11.1 OpenCode 设计

OpenCode 的 TUI 基于以下关键技术：

- **@opentui/core** + **@opentui/solid** — 自研终端 UI 框架（基于 SolidJS）
- **@opentui/keymap** — 键盘快捷键管理
- **node-pty** — 伪终端（用于内嵌 shell）
- **SolidJS 响应式** — 流式 UI 更新

**关键模式：**
- 流式渲染推理 token（与文本 token 分开展示）
- 权限请求内联在对话流中
- 工具调用展示工具名和参数，可展开查看结果
- Tab 切换代理
- 内联代码差异展示

### 11.2 Open-AwA 前端现状

- React + Web 界面
- SSE/WebSocket 流式渲染
- 状态管理：Zustand

### 11.3 可借鉴模式

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P2** | 工具调用内联展示 | 在对话流中展示工具调用卡片（可展开） |
| **P2** | 权限请求 UI | 工具执行前的权限确认弹窗 |
| **P3** | 代理切换 UI | 快捷切换不同权限级别的代理 |

---

## 12. CI/CD 与质量基础设施

### 12.1 OpenCode 设计

**GitHub Actions 工作流矩阵：**

| 工作流 | 用途 |
|--------|------|
| `test.yml` | 主测试套件 |
| `typecheck.yml` | TypeScript 类型检查 |
| `publish.yml` | npm 发布 |
| `deploy.yml` | Web/Console 部署 |
| `beta.yml` | Beta 版本发布 |
| `review.yml` | AI 代码审查 |
| `triage.yml` | Issue 自动分类 |
| `duplicate-issues.yml` | 重复 Issue 检测 |
| `close-issues.yml` | 过期 Issue 关闭 |
| `close-prs.yml` | 过期 PR 关闭 |
| `pr-management.yml` | PR 自动管理 |
| `pr-standards.yml` | PR 标准检查 |
| `compliance-close.yml` | 合规性关闭 |
| `notify-discord.yml` | Discord 通知 |
| `stats.yml` | 统计收集 |
| `docs-update.yml` | 文档更新 |
| `docs-locale-sync.yml` | 多语言同步 |

**AI 驱动的自动化：**

```yaml
# .github/workflows/triage.yml — AI 自动分类 Issues
# .github/workflows/review.yml — AI 代码审查
# .opencode/agent/triage.md — AI Issue 分类代理
# .opencode/agent/duplicate-pr.md — AI PR 重复检测代理
```

**Changeset 版本管理：**
- 使用 `@changesets/cli` 进行语义化版本管理
- 每个 PR 需要包含 changeset 文件
- 发布时自动生成 CHANGELOG

### 12.2 改进建议

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P2** | AI Issue 分类 | 自动为 Issues 添加标签和优先级 |
| **P2** | AI PR 审查 | 自动审查 PR 并提供反馈 |
| **P3** | 重复 Issue 检测 | AI 检测重复的 Issues |
| **P3** | PR 老化管理 | 自动关闭过期 PR，提醒 reviewer |

---

## 13. 改进优先级与实施路径

### 13.1 优先级定义

- **P0（立即实施）**：高价值、低成本、可直接提升用户体验
- **P1（短期实施）**：高价值、中等成本、1-2 周内完成
- **P2（中期实施）**：中等价值或高成本、1 个月内完成
- **P3（长期规划）**：需要架构调整、2-3 个月完成

### 13.2 实施阶段

| 阶段 | 优先级范围 | 改进项数量 | 预估时间 |
|------|-----------|-----------|---------|
| 阶段一：Agent 权限增强 | P0 | 4 | 3-5 天 |
| 阶段二：上下文压缩 | P0 | 3 | 3-5 天 |
| 阶段三：工具注册中心 | P0+P1 | 4 | 5-7 天 |
| 阶段四：技能系统增强 | P1 | 4 | 5-7 天 |
| 阶段五：插件 Hook 系统 | P1 | 4 | 5-7 天 |
| 阶段六：配置与命令系统 | P1+P2 | 7 | 7-10 天 |
| 阶段七：架构与质量 | P2+P3 | 7 | 10-14 天 |

### 13.3 技术可行性评估

| 改进项 | 后端改动 | 前端改动 | 数据库改动 | 风险 |
|--------|---------|---------|-----------|------|
| 代理权限规则 | agent.py 增加 permissions 字段 | 代理选择 UI | Agent 表增加 permissions 列 | 低 |
| 运行时权限请求 | 新增 PermissionManager | 权限请求弹窗 | 新增 PermissionRequest 表 | 中 |
| 上下文压缩 | 新增 CompactionManager | 无 | 无 | 中 |
| 工具注册中心 | 新增 ToolRegistry | 无 | 无（架构变更） | 中 |
| 分层配置 | 新增 ConfigManager | 设置页调整 | 无 | 低 |
| 事件溯源 | 新增 EventStore | 审计面板 | 新增 events 表 | 高 |
| 插件 Hook | PluginManager 扩展 | 无 | 无 | 中 |

---

> **文档版本**：v1.0
> **作者**：Claude Code AI 分析生成
> **下次更新**：阶段实施完成后更新实施结果
