# 记忆管理内置工具 Spec

## Why

当前 AI Agent 在对话过程中可以通过 `task_*` 系列工具管理任务、子代理和团队，但**完全无法操作自身的记忆系统**。Agent 无法主动"记住"用户偏好、"回忆"历史上下文、"遗忘"过时信息或"检索"相关经验。这使得跨会话的上下文延续只能依赖人类手动管理，Agent 缺乏长期记忆的可编程能力。

本 spec 新增 `memory_*` 内置工具集，让 Agent 能在工具调用环节直接操作短期记忆和长期记忆，实现自主记忆管理。

## What Changes

- 在 `backend/core/builtin_tools/` 下新增 `memory_tools.py` 模块，实现记忆管理工具类
- 在 `builtin_tool_manager` 中注册 `memory_*` 工具的定义和分发映射
- 所有 `memory_*` 工具遵循 `builtin_` 前缀约定，走 executor 的 `builtin_` 分发分支
- 前端无需改动

## 工具功能清单

### 1. `memory_remember` — 记住某事
- 将一段重要信息存入长期记忆
- 参数：`content`（必填，记忆内容）、`importance`（可选，重要度 0.0-1.0，默认 0.5）
- 行为：调用 `MemoryManager.add_long_term_memory()`
- 返回值：记忆 ID 和确认信息

### 2. `memory_recall` — 回忆/检索记忆
- 根据查询关键词检索长期记忆（混合搜索：向量 + 关键词）
- 参数：`query`（必填，搜索关键词）、`limit`（可选，返回条数，默认 5）
- 行为：调用 `MemoryManager.vector_search_memories()` 即后端已有的 `/memory/vector-search`
- 返回值：匹配的记忆列表（id、内容片段、重要度、置信度）

### 3. `memory_forget` — 遗忘记忆
- 删除指定 ID 的长期记忆
- 参数：`memory_id`（必填，记忆 ID）
- 行为：调用 `MemoryManager.delete_long_term_memory()`，需校验 user_id
- 返回值：成功/失败确认

### 4. `memory_list` — 列出近期记忆
- 列出最近存入的长期记忆摘要
- 参数：`limit`（可选，返回条数，默认 10）、`include_archived`（可选，默认 false）
- 行为：查询 LongTermMemory 表，按时间倒序
- 返回值：记忆列表（id、内容摘要、重要度、创建时间、归档状态）

### 5. `memory_stats` — 查看记忆统计
- 查看当前记忆系统的整体统计信息
- 参数：无
- 行为：调用 `MemoryManager.get_enhanced_stats()`
- 返回值：总记忆数、活跃数、归档数、平均置信度、平均质量评分、总访问次数

## Impact

- Affected specs: 无（全新功能）
- Affected code:
  - `backend/core/builtin_tools/memory_tools.py` — **新增**
  - `backend/core/builtin_tools/manager.py` — 注册新工具定义和映射
  - `backend/core/builtin_tools/__init__.py` — 导出新模块（如需要）
- 不涉及：前端、API 路由、数据库模型

## ADDED Requirements

### Requirement: memory_remember
系统 SHALL 提供一个内置工具 `memory_remember`，允许 Agent 将一段重要信息存入长期记忆。

#### Scenario: 正常存入记忆
- **GIVEN** Agent 在工具调用中收到 `memory_remember` 调用
- **WHEN** 参数 `content` 为有效字符串
- **THEN** 系统调用 MemoryManager 将该内容写入 LongTermMemory 表
- **AND** 返回 `{"ok": true, "memory_id": <id>, "message": "已记住"}`

#### Scenario: 缺少必填参数
- **GIVEN** Agent 调用 `memory_remember`
- **WHEN** 未提供 `content` 参数
- **THEN** 返回 `{"ok": false, "error": "缺少必填参数: content"}`

### Requirement: memory_recall
系统 SHALL 提供一个内置工具 `memory_recall`，允许 Agent 根据查询词检索相关长期记忆。

#### Scenario: 检索到匹配记忆
- **GIVEN** 系统中存在多条长期记忆
- **WHEN** Agent 调用 `memory_recall` 传入 `query="用户偏好"`
- **THEN** 系统执行向量+关键词混合搜索
- **AND** 返回匹配的记忆列表，每条包含 id、content（截断至 200 字）、importance、confidence

#### Scenario: 无匹配记忆
- **GIVEN** 系统中无相关记忆
- **WHEN** Agent 调用 `memory_recall`
- **THEN** 返回 `{"ok": true, "memories": [], "message": "未找到相关记忆"}`

### Requirement: memory_forget
系统 SHALL 提供一个内置工具 `memory_forget`，允许 Agent 删除指定 ID 的长期记忆。

#### Scenario: 正常删除
- **GIVEN** 存在 ID 为 42 的长期记忆
- **WHEN** Agent 调用 `memory_forget` 传入 `memory_id=42`
- **THEN** 系统删除该记忆
- **AND** 返回 `{"ok": true, "message": "已遗忘记忆 #42"}`

#### Scenario: 记忆不存在
- **GIVEN** 不存在 ID 为 999 的长期记忆
- **WHEN** Agent 调用 `memory_forget` 传入 `memory_id=999`
- **THEN** 返回 `{"ok": false, "error": "记忆不存在: 999"}`

### Requirement: memory_list
系统 SHALL 提供一个内置工具 `memory_list`，允许 Agent 列出近期长期记忆摘要。

#### Scenario: 列出记忆
- **GIVEN** 系统中存在多条长期记忆
- **WHEN** Agent 调用 `memory_list` 传入 `limit=5`
- **THEN** 返回最近 5 条记忆
- **AND** 每条包含 id、content（截断至 100 字）、importance、created_at、archive_status

#### Scenario: 无记忆
- **GIVEN** 系统中无长期记忆
- **WHEN** Agent 调用 `memory_list`
- **THEN** 返回 `{"ok": true, "memories": [], "message": "暂无长期记忆"}`

### Requirement: memory_stats
系统 SHALL 提供一个内置工具 `memory_stats`，允许 Agent 查看当前记忆系统的统计信息。

#### Scenario: 查看统计
- **GIVEN** 系统中存在记忆数据
- **WHEN** Agent 调用 `memory_stats`
- **THEN** 返回统计信息：总记忆数、活跃数、归档数、平均置信度、平均质量评分、总访问次数

## 工具命名与参数设计

| 工具名 | 描述 | 必填参数 | 可选参数 |
|--------|------|----------|----------|
| `memory_remember` | 存储一段重要信息到长期记忆 | `content` | `importance`(0.0-1.0, 默认 0.5) |
| `memory_recall` | 根据查询检索相关记忆 | `query` | `limit`(默认 5, 最大 20) |
| `memory_forget` | 删除指定记忆 | `memory_id` | — |
| `memory_list` | 列出近期记忆摘要 | — | `limit`(默认 10, 最大 50), `include_archived`(默认 false) |
| `memory_stats` | 查看记忆系统统计 | — | — |
