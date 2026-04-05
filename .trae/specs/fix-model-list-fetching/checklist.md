# Checklist

## 后端接口修正
- [x] `pricing_manager.py` 中 `models` 用途的后缀正确返回为 `/models`

## 测试用例更新
- [x] 相关的测试用例 `test_provider_endpoint_resolution.py` 更新为验证 `/models` 拼接逻辑
- [x] 后端单元测试全部运行通过

## 验证
- [x] 系统能向供应商正确的端点获取模型列表，不再提示“已回退到本地模型列表”