# Tasks
- [x] Task 1: 修复后端 `PricingManager` 更新字段白名单
  - [x] SubTask 1.1: 在 `backend/billing/pricing_manager.py` 的 `CONFIG_UPDATE_ALLOWED_FIELDS` 中增加 `display_name`, `api_endpoint`, `selected_models`, `icon`, `sort_order`, `max_tokens_limit`, `top_k`。
- [x] Task 2: 修复后端拉取模型列表时的 API Key 回退逻辑
  - [x] SubTask 2.1: 在 `backend/billing/routers/billing.py` 的 `get_models_by_provider` 函数中，将 `actual_api_key` 的判断条件修改为 `if request_api_key else ...`，确保空字符串被正确忽略并使用保存值。
- [x] Task 3: 补充测试用例
  - [x] SubTask 3.1: 在 `backend/tests/test_provider_endpoint_resolution.py` 中补充测试用例，验证当 `api_key=""` 时，系统是否会正确使用保存于 DB 中的密钥。
  - [x] SubTask 3.2: 执行后端测试，确保 `pytest backend/tests/test_provider_endpoint_resolution.py` 通过。
