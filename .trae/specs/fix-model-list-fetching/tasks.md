# Tasks

- [x] 任务1：修正后端模型列表端点映射
  - [x] 子任务1.1：修改 `backend/billing/pricing_manager.py` 中的 `get_provider_endpoint_suffixes` 方法，将 `models` 的后缀修改为 `/models`

- [x] 任务2：更新并运行后端测试用例
  - [x] 子任务2.1：修改 `backend/tests/test_provider_endpoint_resolution.py`，更新与 `/models` 端点相关的断言
  - [x] 子任务2.2：运行 `pytest` 测试并确保所有用例通过

# Task Dependencies
- 任务2 依赖 任务1 的完成