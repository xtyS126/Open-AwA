# Checklist

## 数据模型
- [ ] `ConversationRecord` SQLite 表结构设计合理，字段完整覆盖 spec 要求
- [ ] SQLAlchemy 模型可正常创建表（无迁移冲突）
- [ ] `llm_input` / `llm_output` / `metadata` 使用 JSON/TEXT 类型，序列化/反序列化正确

## 记录器
- [ ] `ConversationRecorder` 可正常实例化且绑定到 db session
- [ ] `record()` 方法可正确写入单条记录
- [ ] 异步批量写入队列在高频调用下稳定，不丢数据，不阻塞主流程
- [ ] 数据收集开关基于用户偏好，未登录或未开启时不写入

## Agent 链路埋点
- [ ] `agent.process()` 在意图识别阶段写入记录
- [ ] 技能/插件匹配阶段写入记录
- [ ] `executor._call_llm_api()` 在成功和失败路径均写入记录
- [ ] 工具执行结果写入记录
- [ ] `feedback.generate_response()` 完成后写入记录
- [ ] 所有埋点均为非阻塞（asyncio.create_task），不影响聊天响应时间

## 后端导出接口
- [ ] `GET /api/conversations/records` 返回预览列表，字段完整
- [ ] `GET /api/conversations/export` 返回流式 JSONL，Content-Type 为 application/x-ndjson
- [ ] 导出接口支持 `start_time` / `end_time` 参数过滤
- [ ] 导出接口在 10000 条记录下内存占用 < 50MB
- [ ] `DELETE /api/conversations/records/cleanup` 支持 `days` 参数，默认 30
- [ ] `GET /api/conversations/collection-status` 正确返回当前用户偏好
- [ ] `PUT /api/conversations/collection-status` 可更新收集开关状态

## 前端设置页
- [ ] 设置页包含数据收集开关
- [ ] 预览列表正常展示最近记录
- [ ] 导出功能提供时间范围选择并触发下载
- [ ] 清理功能有确认弹窗并反馈删除数量
- [ ] 前端类型检查通过

## 端到端
- [ ] 开启收集 → 聊天 → 数据库有新记录
- [ ] 导出 JSONL 行数与查询记录数一致
- [ ] 关闭收集 → 聊天 → 无新记录
- [ ] 清理接口正确删除过期数据
