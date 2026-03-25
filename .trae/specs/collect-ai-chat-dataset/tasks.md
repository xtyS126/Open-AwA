# Tasks
- [ ] Task 1: 确认现有 Agent/Executor/Feedback 执行链路的关键节点和数据流
  - [ ] SubTask 1.1: 阅读 `agent.py` 的 `process()` 主流程，确认关键节点顺序
  - [ ] SubTask 1.2: 阅读 `executor.py` 的 `_call_llm_api()`，确认 LLM 调用输入输出结构
  - [ ] SubTask 1.3: 阅读 `feedback.py` 的 `generate_response()`，确认最终回复结构
  - [ ] SubTask 1.4: 确认现有 Session / User 上下文获取方式

- [ ] Task 2: 新增 conversation_recorder.py 数据记录器
  - [ ] SubTask 2.1: 设计 SQLite 表结构和 SQLAlchemy 模型
  - [ ] SubTask 2.2: 实现异步批量写入队列（避免阻塞主流程）
  - [ ] SubTask 2.3: 实现 `ConversationRecorder.record()` 接口，按节点类型写入对应记录
  - [ ] SubTask 2.4: 实现数据收集开关的内存状态（基于 current_user 的偏好设置）
  - [ ] SubTask 2.5: 验证记录器在高频调用下不导致内存泄漏

- [ ] Task 3: 在 Agent 链路关键节点埋点
  - [ ] SubTask 3.1: 在 `agent.process()` 的意图识别阶段调用记录器
  - [ ] SubTask 3.2: 在技能/插件匹配阶段调用记录器
  - [ ] SubTask 3.3: 在 `executor._call_llm_api()` 成功和失败路径均调用记录器
  - [ ] SubTask 3.4: 在工具执行结果处调用记录器
  - [ ] SubTask 3.5: 在 `feedback.generate_response()` 完成时调用记录器
  - [ ] SubTask 3.6: 确保埋点为非阻塞调用（使用 asyncio.create_task 异步写入）

- [ ] Task 4: 实现后端导出接口
  - [ ] SubTask 4.1: 实现 `GET /api/conversations/records`（预览最近 N 条）
  - [ ] SubTask 4.2: 实现 `GET /api/conversations/export`（JSONL 流式下载，支持 start_time / end_time 参数）
  - [ ] SubTask 4.3: 实现 `DELETE /api/conversations/records/cleanup`（清理 N 天前数据）
  - [ ] SubTask 4.4: 实现 `GET /api/conversations/collection-status`（查询当前收集开关状态）
  - [ ] SubTask 4.5: 实现 `PUT /api/conversations/collection-status`（更新收集开关状态）
  - [ ] 验证: 导出接口在数据量大时内存占用可控（流式响应）

- [ ] Task 5: 前端设置页接入
  - [ ] SubTask 5.1: 在设置页新增"数据收集" tab 或入口
  - [ ] SubTask 5.2: 展示收集开关（toggle）
  - [ ] SubTask 5.3: 接入预览接口，展示最近记录列表
  - [ ] SubTask 5.4: 接入导出接口，提供时间范围选择和下载触发
  - [ ] SubTask 5.5: 接入清理接口，提供确认弹窗和结果反馈
  - [ ] SubTask 5.6: 运行前端类型检查

- [ ] Task 6: 端到端验证
  - [ ] SubTask 6.1: 开启收集 → 发起一条聊天 → 确认数据写入数据库
  - [ ] SubTask 6.2: 调用导出接口 → 确认返回有效 JSONL → 验证 JSON 行数与数据库记录一致
  - [ ] SubTask 6.3: 关闭收集 → 发起聊天 → 确认无新记录写入
  - [ ] SubTask 6.4: 清理 0 天数据 → 确认返回删除数量

# Task Dependencies
- [Task 2] 依赖 [Task 1]
- [Task 3] 依赖 [Task 1] 和 [Task 2]
- [Task 4] 依赖 [Task 2]
- [Task 5] 依赖 [Task 4]
- [Task 6] 依赖 [Task 3]、[Task 4]、[Task 5]
