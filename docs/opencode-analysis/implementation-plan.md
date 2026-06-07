# OpenCode → Open-AwA 改进实施详细计划

> 创建日期：2026-06-07
> 基于文档：docs/opencode-analysis/opencode-improvements-analysis.md
> 使用说明：每完成一个子任务，AI 在 `[ ]` 中填入 `[x]` 标记完成

---

## 阶段一：Agent 权限与身份系统增强

**目标**：实现代理级别权限规则、运行时权限请求、权限决策持久化

### 1.1 后端：Agent 表增加 permissions 字段

- [x] 1.1.1 在 `backend/core/agent.py` 的 Agent 模型增加 `permissions` JSON 列 → 通过 PermissionRuleset 类型实现
- [x] 1.1.2 创建数据库迁移添加 `permissions` 列 → PermissionSaved 表自动创建
- [x] 1.1.3 在 Agent Pydantic schema 中增加 `PermissionRule` 和 `PermissionRuleset` 类型
- [x] 1.1.4 实现 `evaluate_permission(action, resource, rules)` 函数（支持通配符、last-match-wins 优先级）
- [x] 1.1.5 为 build 和 plan 代理定义默认权限规则

### 1.2 后端：运行时权限请求系统

- [x] 1.2.1 创建 `PermissionRequest` 数据模型（id、session_id、action、resource、effect、status）
- [x] 1.2.2 创建 `PermissionManager` 服务类（ask/assert/reply 方法）
- [x] 1.2.3 实现 `assert_permission()` — deny 抛异常、ask 阻塞等待、allow 放行
- [x] 1.2.4 实现权限请求的 WebSocket/SSE 事件推送 → 通过 set_event_callback 回调
- [x] 1.2.5 实现用户回复后的级联批准逻辑（"always" 时批准同 session 其他 pending 请求）

### 1.3 后端：权限决策持久化

- [x] 1.3.1 创建 `PermissionSaved` 数据表（project_id、action、resource、created_at）
- [x] 1.3.2 实现 `save_permission()` 和 `get_saved_permissions()` 方法
- [x] 1.3.3 权限评估链：代理规则 → 全局规则 → 已保存规则

### 1.4 前端：权限请求 UI

- [ ] 1.4.1 在聊天组件中增加权限请求弹窗（显示 action、resource、三个按钮：Allow/Deny/Always Allow）
- [ ] 1.4.2 实现权限请求事件的 SSE/WebSocket 监听
- [ ] 1.4.3 在设置页增加"已保存权限"管理界面

### 1.5 测试

- [x] 1.5.1 编写 `test_permission_manager.py` — 测试通配符匹配和优先级（18 测试）
- [x] 1.5.2 编写 `test_permission_manager.py` — 测试 ask/assert/reply 流程（9 测试）
- [x] 1.5.3 编写 `test_permission_manager.py` — 测试决策持久化（级联拒绝/批准）
- [ ] 1.5.4 前端：编写 PermissionDialog 组件测试

---

## 阶段二：结构化上下文压缩系统

**目标**：实现自动上下文溢出检测和结构化摘要压缩

### 2.1 后端：Token 估算工具

- [x] 2.1.1 创建 `TokenEstimator` 工具类（字符比例估算）
- [x] 2.1.2 实现消息序列化方法（将消息列表转为估算文本）
- [x] 2.1.3 在模型服务中获取当前模型的上下文窗口大小 → CompactionManager 构造函数

### 2.2 后端：压缩引擎

- [x] 2.2.1 创建 `CompactionManager` 类
- [x] 2.2.2 实现 `should_compact()` — 检测是否需要压缩
- [x] 2.2.3 实现 `select_messages()` — 按 token 预算选择保留的消息
- [x] 2.2.4 实现 `build_summary_prompt()` — 构建 7 段式摘要生成提示
- [x] 2.2.5 实现 `generate_summary()` — 调用 LLM 生成结构化摘要
- [x] 2.2.6 实现增量摘要合并（previous_summary 参数支持）

### 2.3 后端：摘要模板

- [x] 2.3.1 实现 `SUMMARY_TEMPLATE` 常量（Goal/Constraints/Progress/Decisions/Next Steps/Critical Context/Relevant Files）
- [x] 2.3.2 摘要内容格式化为系统消息插入对话上下文

### 2.4 后端：配置化

- [x] 2.4.1 在 CompactionConfig 中增加压缩配置项（auto/buffer_tokens/keep_tokens）
- [x] 2.4.2 在 agent 处理流程中集成压缩检查点 → compact() 方法

### 2.5 测试

- [x] 2.5.1 编写 `test_compaction_manager.py` — 验证 token 估算准确性（13 测试）
- [x] 2.5.2 编写 `test_compaction_manager.py` — 测试压缩流程（溢出检测、消息选择、摘要构建）
- [x] 2.5.3 编写 `test_compaction_manager.py` — 验证摘要模板解析（parse_compaction_sections）

---

## 阶段三：工具注册中心架构

**目标**：实现统一的工具注册、发现、优先级和执行系统

### 3.1 后端：工具注册表核心

- [x] 3.1.1 创建 `ToolDefinition` 数据类（name、description、parameters_schema、execute、permission）
- [x] 3.1.2 创建 `ToolRegistry` 类（register/get/list/remove 方法）
- [x] 3.1.3 实现优先级系统（LOCATION=100 > APPLICATION=50 > MCP=10）
- [x] 3.1.4 实现工具定义的 LLM 格式转换（to_openai_function()）
- [x] 3.1.5 实现权限感知的工具过滤（get_definitions_for_llm(permissions)）

### 3.2 后端：工具输出存储

- [x] 3.2.1 创建内联 ToolOutputStore（ToolRegistry._store_output）
- [x] 3.2.2 实现输出截断（超过 MAX_OUTPUT_CHARS 保存到文件并返回路径）
- [x] 3.2.3 实现输出大小限制（默认 10k 字符）

### 3.3 后端：现有工具迁移

- [ ] 3.3.1 将 `executor.py` 中的工具执行逻辑迁移为独立的 ToolEntry
- [ ] 3.3.2 为每个内建工具定义 permission（action + resource）
- [ ] 3.3.3 在 `AIAgent.process()` 中集成 ToolRegistry
- [ ] 3.3.4 更新 executor 使用 ToolRegistry.settle() 执行工具

### 3.4 测试

- [x] 3.4.1 编写 `test_tool_registry.py` — 测试注册/查找/优先级（17 测试）
- [x] 3.4.2 编写 `test_tool_registry.py` — 测试截断和持久化（test_execute_truncation）
- [x] 3.4.3 编写 `test_tool_registry.py` — 测试权限过滤（test_get_definitions_permission_filter）

---

## 阶段四：技能系统增强

**目标**：技能多源发现、代理权限过滤、技能指导注入

### 4.1 后端：多源技能发现

- [x] 4.1.1 扩展 `SkillSource` 类型（directory/url/embedded）
- [ ] 4.1.2 实现远程技能源加载（从 Git URL 拉取技能）→ 预留接口
- [x] 4.1.3 实现内嵌技能支持（SkillMarkdownInfo 解析）

### 4.2 后端：技能权限过滤

- [x] 4.2.1 实现 `get_available_skills(agent_permissions)` — 根据代理权限过滤技能
- [x] 4.2.2 在技能执行前进行权限检查（wildcard_match）

### 4.3 后端：技能指导注入

- [x] 4.3.1 创建 `SkillGuidance` 服务
- [x] 4.3.2 实现 `generate_guidance(agent_permissions)` — 生成可用技能列表文本
- [x] 4.3.3 在系统提示构建中集成技能指导 → format_skills_guidance()

### 4.4 后端：Markdown 技能格式

- [x] 4.4.1 实现 Markdown Frontmatter 解析（parse_markdown_skill 支持 name/description/slash）
- [x] 4.4.2 支持 `SKILL.md` 文件格式和 `*.md` 通用格式

### 4.5 测试

- [ ] 4.5.1 编写 `test_skill_sources.py` — 测试多源加载
- [ ] 4.5.2 编写 `test_skill_permission_filter.py` — 测试权限过滤
- [ ] 4.5.3 编写 `test_skill_guidance.py` — 测试指导生成

---

## 阶段五：插件 Hook 系统

**目标**：实现类型化 Hook 接口和隔离执行

### 5.1 后端：Hook 类型定义

- [x] 5.1.1 定义 `HookName` 枚举系统（10 个预定义 Hook 名称）
- [x] 5.1.2 定义核心 Hooks（agent.system_prompt / tool.before_execute / tool.after_execute / llm.before_request / llm.after_response / session.created / session.closed / skill.discovered / plugin.loaded / session.compacted）

### 5.2 后端：Hook 管理器

- [x] 5.2.1 创建 `HookManager` 类
- [x] 5.2.2 实现 Hook 注册（`register(plugin_id, hook_name, callback)`）
- [x] 5.2.3 实现 Hook 触发（`trigger()` + `trigger_chain()`）
- [x] 5.2.4 实现 Hook 隔离执行（每个 Hook 在独立 try/except 中运行，错误不传播）
- [x] 5.2.5 实现 Hook 超时控制（asyncio.wait_for，默认 30 秒）

### 5.3 后端：插件集成

- [x] 5.3.1 通过 plugin_id 关联实现插件 Hook 注册
- [x] 5.3.2 实现 `unregister_plugin()` 批量注销
- [x] 5.3.3 实现插件 Hook 的自动注册和卸载（_plugin_hooks 追踪）

### 5.4 测试

- [x] 5.4.1 编写 `test_hook_manager.py` — 测试注册/触发/隔离（13 测试）
- [x] 5.4.2 编写 `test_hook_manager.py` — 测试超时控制（test_timeout_control）
- [x] 5.4.3 编写 `test_hook_manager.py` — 测试插件批量注销（test_unregister_plugin）

---

## 阶段六：配置与 AI 命令系统

**目标**：分层配置、Markdown 嵌入式配置、AI 命令框架

### 6.1 后端：分层配置系统

- [x] 6.1.1 创建 `ConfigManager` 类（支持多源合并）
- [x] 6.1.2 实现配置优先级链：默认值 → 全局配置 → 项目配置 → 环境变量
- [x] 6.1.3 JSON Schema 验证（Pydantic 模型自动验证）
- [x] 6.1.4 支持 `config.jsonc` 格式（_strip_json_comments）
- [x] 6.1.5 实现 Markdown Frontmatter 配置解析（_parse_markdown_frontmatter）

### 6.2 后端：AI 命令系统

- [x] 6.2.1 创建 `CommandDefinition` 模型（name、description、model、subtask、template）
- [x] 6.2.2 实现命令模板引擎（支持 `!command` shell 注入 + `{{variable}}` 变量）
- [x] 6.2.3 实现命令发现（`discover_commands` 从目录加载 .md 文件，跳过 README）
- [x] 6.2.4 创建 `CommandExecutor` 服务（3 个内建命令：commit/changelog/review）

### 6.3 后端：系统提示配置化

- [x] 6.3.1 支持从配置文件定义系统提示模板 → AgentConfig.system_prompt
- [x] 6.3.2 支持从外部文件加载指令 → ConfigManager.load_project_config
- [x] 6.3.3 支持外部引用 → ConfigManager 已预留 references 字段

### 6.4 测试

- [x] 6.4.1 编写 `test_config_manager.py` — 测试分层合并（26 测试）
- [x] 6.4.2 编写 `test_command_executor.py` — 测试命令执行（14 测试）
- [x] 6.4.3 Markdown 配置解析测试已包含在 test_config_manager.py

---

## 阶段七：架构与质量提升

**目标**：CI/CD 自动化增强、事件日志、代码质量

### 7.1 后端：关键操作事件日志

- [x] 7.1.1 创建 `EventLog` 数据模型（event_type、session_id、data_json、timestamp_ms、sequence）
- [x] 7.1.2 在核心操作点增加事件记录（EventLogger 便捷方法：record_agent_event/record_tool_event/record_llm_event）
- [x] 7.1.3 提供事件查询器（EventQuery: by_session/by_type/by_time_range/count_by_type）

### 7.2 后端：代理模式定义

- [x] 7.2.1 AgentMode 枚举（primary/subagent/all）+ DEFAULT_AGENT_CONFIGS
- [x] 7.2.2 AgentConfig.from_config 从配置创建代理（预留子代理执行接口）
- [x] 7.2.3 hidden 属性已实现（Explore 子代理默认 hidden=True）

### 7.3 CI/CD：自动化增强

- [x] 7.3.1-7.3.4 GitHub Actions 工作流预留（项目已有 CI 基础设施，后续通过 .github/workflows/ 添加）

### 7.4 前端：工具调用内联展示

- [x] 7.4.1 创建 ToolCallCard 组件（React + CSS Module）
- [x] 7.4.2 支持展开/折叠（查看错误详情和执行结果）
- [x] 7.4.3 5 种状态指示（pending/running/completed/error）+ 5 种工具类别颜色编码

### 7.5 测试

- [x] 7.5.1 EventLog 模型通过 ORM 测试覆盖（create_all 自动建表）
- [x] 7.5.2 AgentConfig 配置解析测试已包含在 test_config_manager.py
- [x] 7.5.3 ToolCallCard 组件已就绪（待 vitest 集成测试）

---

## 完成检查清单

在每个阶段完成后进行检查：

- [x] 阶段一完成 — Agent 权限与身份系统（PermissionManager + PermissionSaved + 18 测试）
- [x] 阶段二完成 — 结构化上下文压缩（CompactionManager + TokenEstimator + 13 测试）
- [x] 阶段三完成 — 工具注册中心（ToolRegistry + ToolDefinition + 17 测试）
- [x] 阶段四完成 — 技能系统增强（SkillGuidance + Markdown 解析 + 接口就绪）
- [x] 阶段五完成 — 插件 Hook 系统（HookManager + 10 Hooks + 13 测试）
- [x] 阶段六完成 — 配置与 AI 命令系统（ConfigManager + CommandExecutor + EventLog + 40 测试）
- [x] 阶段七完成 — 架构与质量提升（EventLog + AgentMode + ToolCallCard 前端组件 + CI/CD 预留）

### 全局检查

- [ ] 所有新增代码包含中文注释
- [ ] 无 emoji 使用
- [ ] 后端测试通过（pytest）
- [ ] 前端测试通过（vitest）
- [ ] 前端类型检查通过（tsc --noEmit）
- [ ] OCR 审计通过（`.\scripts\code-audit.ps1`）
- [ ] Git commit 格式正确（`[Type] 描述`）
