# 验收清单

## 1. 数据库与模型
- [x] `ConversationRecord` 模型已存在，包含必要字段：session_id、user_id、node_type、user_message、timestamp、provider、model、llm_input、llm_output、llm_tokens_used、execution_duration_ms、status、error_message、metadata
- [x] 启动时可自动创建对应表（开发环境 SQLite）

## 2. 数据收集器能力
- [x] `conversation_recorder.py` 提供统一记录接口
- [x] 使用异步队列/后台任务写入，主流程非阻塞
- [x] 支持按用户开关（enabled）控制是否写入
- [x] 支持返回运行时状态统计（队列大小、丢弃计数等）

## 3. 链路埋点完整性
- [x] `agent.process()` 在意图识别阶段写入记录
- [x] 技能/插件匹配阶段写入记录
- [x] `executor._call_llm_api()` 在成功和失败路径均写入记录
- [x] 工具执行结果写入记录
- [x] `feedback.generate_response()` 完成后写入记录
- [x] 所有埋点均为非阻塞（asyncio.create_task），不影响聊天响应时间

## 4. 后端接口能力
- [x] `GET /api/conversations/records` 返回预览列表，字段完整
- [x] `GET /api/conversations/export` 返回流式 JSONL，Content-Type 为 application/x-ndjson
- [x] 导出接口支持 `start_time` / `end_time` 参数过滤
- [x] `DELETE /api/conversations/records/cleanup` 支持 `days` 参数，默认 30
- [x] `GET /api/conversations/collection-status` 正确返回当前用户偏好
- [x] `PUT /api/conversations/collection-status` 可更新收集开关状态

## 5. 前端设置页能力
- [x] 设置页包含数据收集开关
- [x] 预览列表正常展示最近记录
- [x] 导出功能提供时间范围选择并触发下载
- [x] 清理功能有确认弹窗并反馈删除数量
- [x] 前端类型检查通过

## 6. 端到端验证（本地）
- [x] 开启收集 → 写入一条记录 → `/records` 可见
- [x] `/export` 返回有效 JSONL，且行数与数据库记录一致
- [x] 关闭收集后再写入，数据库记录数不再增长
- [x] `cleanup?days=0` 返回删除数量且大于等于 1
