# 修复供应商密钥与导入模型状态同步缺陷

## Why
目前在前端进行模型供应商的密钥配置和模型导入时存在两个严重缺陷：
1. 后端 `pricing_manager.py` 中的 `update_configuration` 接口白名单校验（`CONFIG_UPDATE_ALLOWED_FIELDS`）遗漏了 `display_name`、`api_endpoint`、`selected_models` 等字段，导致配置保存和模型导入操作被拦截并产生日志警告。
2. 前端点击“获取模型列表”时，若当前密码输入框为空，会传递空字符串 `""` 给后端。后端的判定逻辑 (`if request_api_key is not None`) 错误地将空字符串作为有效凭据，覆盖了数据库中已经保存的真实 API Key，最终导致上游返回 401 认证失败，迫使需要在每次获取前重新输入密钥。

## What Changes
- **修改后端允许更新字段白名单**：在 `PricingManager.CONFIG_UPDATE_ALLOWED_FIELDS` 中补充 `display_name`, `api_endpoint`, `selected_models`, `icon`, `sort_order`, `max_tokens_limit`, `top_k` 等被遗漏的模型配置字段。
- **修正模型列表拉取的密钥判定回退逻辑**：在 `/api/billing/models-by-provider/{provider}` 的实现中，将 `actual_api_key = request_api_key if request_api_key is not None else ...` 改为使用真值判定 `actual_api_key = request_api_key if request_api_key else ...`。这样当传入空字符串时，能够正确回退使用数据库中已保存的 API Key。
- **补充测试用例**：编写针对空字符串 API Key 时能够正确回退使用已有配置的后端测试用例，并在前端保证获取模型、保存配置环节的平滑性。

## Impact
- Affected specs: 供应商配置模块、模型导入模块
- Affected code: 
  - `backend/billing/pricing_manager.py`
  - `backend/billing/routers/billing.py`
  - `backend/tests/test_provider_endpoint_resolution.py`

## MODIFIED Requirements
### Requirement: 更新供应商配置 (update_configuration)
**变更原因**: 原逻辑拒绝了业务上合理且必需的配置更新。
**修改后**: `CONFIG_UPDATE_ALLOWED_FIELDS` 必须包含所有可以通过前端表单或模型导入操作更新的字段。

### Requirement: 获取模型列表时的凭证透传
**变更原因**: 修复因空字符串导致的数据库有效密钥被覆盖覆盖导致 401 认证失败的问题。
**修改后**: 如果客户端发起的 POST 请求体中 `api_key` 为空字符串或 `None`，后端应当降级读取当前数据库记录中保存的密钥。
