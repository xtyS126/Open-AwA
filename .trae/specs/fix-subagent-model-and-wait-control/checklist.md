# Checklist

## 功能验证

- [x] 前台模式：主 Agent 调用 `task_spawn_agent` (background=false) 后，子代理实际运行并返回真实摘要结果
- [x] 前台模式：前端能收到完整的子代理事件流（subagent_start -> agent_message -> subagent_stop）
- [x] 前台模式：子代理完成后的摘要被主 Agent 作为工具调用结果用于生成回复
- [ ] 前台模式：子代理执行失败时，错误信息能正确传递给主 Agent 和前端
- [x] 后台模式：主 Agent 调用 `task_spawn_agent` (background=true) 后不等待，立即继续下一步
- [x] 后台模式：子代理异步执行的结果通过独立 SSE 事件推送，不阻塞主流程
- [x] 模型选择：LLM 指定 provider/model 时，子代理使用指定模型运行
- [x] 模型选择：LLM 未指定模型时，子代理继承主 Agent 的当前模型
- [x] 模型选择：无法确定模型时，返回明确错误信息而非静默失败

## 代码质量

- [x] 无 `try/except/pass` 或静默吞异常
- [x] 新增函数有完整类型标注
- [x] 日志包含子代理 ID、模型选择等关键上下文
- [x] 资源（AsyncGenerator、数据库连接）正确释放
- [ ] 无引入新的 mypy 错误
- [ ] 无引入新的 bandit 安全问题

## 回归测试

- [x] 现有后台子代理功能不受影响
- [x] 现有工具调用链（非 subagent）不受影响
- [x] 现有 SSE 事件格式兼容
- [x] 前端子代理 UI 组件无回归
