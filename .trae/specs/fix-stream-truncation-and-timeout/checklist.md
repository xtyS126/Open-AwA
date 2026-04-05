# Checklist

## 后端配置修改
- [x] `backend/billing/models.py` 的 `ModelConfiguration` 模型类中已添加 `max_tokens` 字段。
- [x] `backend/billing/pricing_manager.py` 的 `ensure_configuration_schema` 中已添加了对旧数据库结构 `max_tokens` 列的迁移。
- [x] `backend/core/executor.py` 能够根据供应商配置读取出动态 `max_tokens`（并设好了兜底值 8192）。
- [x] `backend/core/model_service.py` 中的 `timeout` 默认值已提升至 120.0 秒。

## 前端配置页与网络解析
- [x] 可以在前端设置页面对应的供应商表单里，查看并修改 `max_tokens` 字段，且能够持久化到后端。
- [x] `api.ts` 中的 `chatAPI.sendMessageStream` 添加了跨包字符的缓冲拼接机制（`buffer`）。
- [x] 确保网络包在行中间截断时，前端 JSON 解析不会报错并将剩余部分保留到下一包一起解析。
- [x] 确保流结束标志 `data: [DONE]` 即使在网络层跨包被拆分，也能被完整拼装和识别并终止流式连接。

## 综合测试
- [x] 执行极长回答模型调用（如带复杂的思维链问题）能正常输出几千字内容而不发生意外中断，且测试 `max_tokens` 小配置能成功提前截断验证生效。
- [x] 前端 TypeScript 编译（`npm run typecheck`）或 ESLint 无报错。
- [x] 后端 Pytest 单元测试全部通过。