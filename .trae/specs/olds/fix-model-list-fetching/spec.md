# Fix Model List Fetching Failure Spec

## Why
在上一次的 API URL 智能处理改造中，为了满足在不同业务场景下自动拼接请求后缀的需求，后端 `pricing_manager.py` 将模型列表请求 (`models`) 和聊天请求 (`chat`) 的端点统一设置为了 `/chat/completions`。然而，对于兼容 OpenAI 接口规范的 API（如 DeepSeek、OpenAI 等），`/chat/completions` 是一个 POST 接口专门用于聊天请求，而获取模型列表应该通过向 `/models` 接口发送 GET 请求来实现。
因此，当系统向 `/chat/completions` 发送 GET 请求时，会导致 API 服务返回 404 或 405 Method Not Allowed 错误。进而触发了系统的错误处理机制，回退到了本地模型列表，并在界面上抛出错误提示 `模型列表获取失败，已回退到本地模型列表`。

## What Changes
- 修改后端 `pricing_manager.py` 中 `get_provider_endpoint_suffixes` 方法，将 `models` 对应的后缀从 `/chat/completions` 修正为 `/models`。
- 修改并同步更新后端测试用例 `test_provider_endpoint_resolution.py`，断言 `models` 的拼接地址正确使用了 `/models`。

## Impact
- Affected specs: 模型列表获取模块。
- Affected code:
  - `backend/billing/pricing_manager.py`
  - `backend/tests/test_provider_endpoint_resolution.py`

## MODIFIED Requirements
### Requirement: 获取模型列表
系统 SHALL 在获取可用模型列表时，自动基于基础 URL 拼接 `/models` 后缀发起 GET 请求。

#### Scenario: 成功获取模型
- **WHEN** 用户点击获取模型列表或切换供应商
- **THEN** 系统向 `<base_url>/models` 发送 GET 请求，正确解析返回结果并显示在界面上，不抛出回退错误提示。
