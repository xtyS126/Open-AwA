# Tasks

- [x] 任务1：数据库与后端接口适配 `max_tokens`
  - [x] 子任务1.1：在 `backend/billing/models.py` 的 `ModelConfiguration` 表中增加 `max_tokens` (Integer) 字段。
  - [x] 子任务1.2：在 `backend/billing/pricing_manager.py` 的 `ensure_configuration_schema` 中添加自动升级表结构（ALTER TABLE ADD COLUMN max_tokens INTEGER DEFAULT 8192）的代码。
  - [x] 子任务1.3：在 `backend/api/schemas.py` 中针对供应商配置的输入和输出结构补充 `max_tokens` 字段。

- [x] 任务2：前端配置页 UI 支持
  - [x] 子任务2.1：在 `frontend/src/features/settings/modelsApi.ts` 相关的配置接口声明中增加 `max_tokens?: number`。
  - [x] 子任务2.2：在 `frontend/src/features/settings/SettingsPage.tsx` 的提供商表单 Modal 中增加“最大生成 Token”的数字输入框。

- [x] 任务3：模型调用层注入自定义 `max_tokens` 及增加超时
  - [x] 子任务3.1：在 `backend/core/executor.py` 的 `_resolve_llm_configuration` 方法中获取当前配置的 `max_tokens` 放入 `resolved` 返回结果中。
  - [x] 子任务3.2：在 `_call_llm_api` 和 `_call_llm_api_stream` 处，将原来硬编码的 1000 替换为获取到的动态值（如果为空则回退到 8192）。
  - [x] 子任务3.3：在 `backend/core/model_service.py` 中，将 `ProviderRequestSpec` 默认 `timeout` 从 30.0 修改为 120.0，并在实例化处相应增加以应对长推理模型。

- [x] 任务4：修复前端 SSE 跨包解析丢失问题
  - [x] 子任务4.1：在 `frontend/src/shared/api/api.ts` 的 `chatAPI.sendMessageStream` 函数中，添加一个 `buffer` 变量累加解码内容。
  - [x] 子任务4.2：修改 `chunk.split('\n')` 逻辑，在最后剩余不完整的换行内容时，将其放入 `buffer` 并在下一次 `reader.read()` 到来时前置拼接。

- [x] 任务5：验证代码稳定性
  - [x] 子任务5.1：使用长推理指令进行模拟测试，确保回复长度远超 1000 个 Token 时不发生截断，且新配置的 Token 生效。
  - [x] 子任务5.2：执行前端与后端的编译和单元测试。