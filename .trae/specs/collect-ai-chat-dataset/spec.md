# AI 聊天调用数据收集与 JSONL 导出 Spec

## Why
当前 AI Agent 在处理用户聊天请求时，所有调用链路（规划、技能匹配、LLM 请求、工具执行、反馈生成等）的中间结果都只存在于内存中，没有持久化，也没有方便的手段将其导出为结构化数据集。这使得用户无法：
- 回顾和复盘某次对话中 AI 的完整思维过程
- 将高质量对话数据导出用于模型微调、数据分析或案例分享
- 在调试时查看每次 LLM 调用的具体输入输出

## What Changes
- 在 Agent 执行链路的关键节点埋点，将每次调用的上下文、输入、输出、耗时、状态等结构化记录下来
- 提供异步批量写入本地 SQLite 的存储后端，避免阻塞主流程
- 提供设置页入口，让用户控制是否开启数据收集
- 提供导出接口，支持按时间范围过滤并以 JSONL 格式流式下载完整数据集
- 提供下载预览入口，支持在页面直接查看最近 N 条记录

## Impact
- Affected specs: 聊天执行链路、数据设置页
- Affected code:
  - `backend/core/agent.py`（执行链路埋点）
  - `backend/core/executor.py`（LLM 调用埋点）
  - `backend/core/feedback.py`（反馈生成埋点）
  - `backend/core/conversation_recorder.py`（新增：数据记录器）
  - `backend/api/routes/conversation.py`（新增：导出接口）
  - `frontend/src/pages/SettingsPage.tsx`（数据收集开关与导出入口）
  - `backend/db/models.py`（新增数据表）

## ADDED Requirements

### Requirement: 对话记录数据模型
系统 SHALL 提供一张 SQLite 本地表，用于存储每次聊天中 Agent 执行链路的结构化记录。

#### Scenario: 记录结构
- **WHEN** 用户发起一次聊天请求，且数据收集开启
- **THEN** 系统应记录以下字段：
  - `id`：全局唯一自增 ID
  - `session_id`：对话会话 ID
  - `user_id`：发起人 ID
  - `user_message`：用户原始输入
  - `timestamp`：记录时间（ISO 8601）
  - `provider`：调用的模型供应商
  - `model`：调用的模型名称
  - `llm_input`：发送给 LLM 的完整消息列表
  - `llm_output`：LLM 返回的原始文本
  - `llm_tokens_used`：消耗的 token 数量（如可获取）
  - `execution_duration_ms`：该步骤耗时（毫秒）
  - `status`：执行状态（success / error / partial）
  - `error_message`：错误信息（如有）
  - `metadata`：扩展字段（JSON 格式，存储意图、技能匹配结果等附加信息）

### Requirement: Agent 链路埋点
系统 SHALL 在 Agent 处理请求的主流程中，在每个关键节点写入执行记录。

#### Scenario: 完整链路记录
- **WHEN** 用户消息进入 Agent.process() 且数据收集开启
- **THEN** 系统应按以下顺序记录调用节点：
  1. **理解/意图识别**：记录解析出的意图类型、实体
  2. **技能/插件匹配**：记录匹配到的技能列表
  3. **LLM 调用**（如有）：记录 provider / model / input / output / tokens / duration
  4. **工具执行**（如有）：记录工具名称、参数、结果
  5. **反馈生成**：记录最终回复文本
- **AND** 每条记录通过异步队列批量写入数据库，不阻塞主流程

### Requirement: 数据收集开关
系统 SHALL 提供设置页开关，允许用户控制是否开启数据收集。

#### Scenario: 开启数据收集
- **WHEN** 用户在设置页打开"收集对话数据"开关
- **THEN** 后续所有聊天请求均记录执行链路数据
- **AND** 已存储的历史数据不受影响

#### Scenario: 关闭数据收集
- **WHEN** 用户在设置页关闭"收集对话数据"开关
- **THEN** 后续聊天请求不再写入记录数据
- **AND** 已存储的历史数据保留

### Requirement: JSONL 导出
系统 SHALL 提供导出接口，允许用户下载完整数据集为 JSONL 文件。

#### Scenario: 按时间范围导出
- **WHEN** 用户在设置页点击"导出对话数据"
- **THEN** 系统应弹出时间范围选择（默认最近 7 天）
- **AND** 点击确认后，后端返回 JSONL 流式下载响应
- **AND** 每个 JSON 行对应一条记录，包含所有记录字段

#### Scenario: 数据预览
- **WHEN** 用户在设置页点击"预览最近数据"
- **THEN** 页面应展示最近 20 条记录的简要列表（session_id、时间、status、模型）

### Requirement: 数据生命周期管理
系统 SHALL 提供基础的数据清理能力。

#### Scenario: 清理旧数据
- **WHEN** 用户在设置页点击"清理 30 天前的数据"
- **THEN** 系统应删除 timestamp 早于 30 天的记录
- **AND** 返回实际删除的记录数量

## MODIFIED Requirements

### Requirement: Agent 执行链路
现有 Agent.process() / Executor._call_llm_api() 等方法在数据收集开启时应调用记录器，不改变现有主逻辑。

## REMOVED Requirements

### Requirement: 无历史数据持久化
**Reason**: 当前 Agent 链路无任何持久化能力，无法满足回顾和导出需求。
**Migration**: 通过新增数据模型和记录器填补此空白。
