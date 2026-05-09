# 检查清单

## 后端检查

- [x] ModelPricing 表 `supports_vision` 和 `is_multimodal` 字段已添加
- [x] `initialize_default_pricing()` 从 model_capabilities.json 自动回填模态数据
- [x] `/billing/models` API 响应中包含 `supports_vision` 和 `is_multimodal` 字段
- [x] 现有数据兼容：已有记录不会因新增字段而报错
- [x] mypy 检查：billing/ 目录零新增错误（98 个已有错误全部在非 billing 文件）

## 前端检查

- [x] `ModelPricing` 接口已扩展 `supports_vision` 和 `is_multimodal` 字段
- [x] 价格表格表头显示"模态"列
- [x] 每个模型行显示正确的模态标签
- [x] 三种标签样式正确渲染：文本(灰色)、文本+图像(蓝色)、文本+图像+音视频(紫色)
- [x] tsc 类型检查通过（零错误）
- [x] 编辑模式不会影响模态标签显示

## 数据检查

- [x] alibaba 所有模型的 `supports_vision`/`is_multimodal` 已确认（修正 qwen-max/qwen-max-2025-01-25）
- [x] openai 所有模型的 `supports_vision`/`is_multimodal` 已确认（修正 gpt-4.1/gpt-4.1-mini/gpt-4.1-nano）
- [x] anthropic 所有模型的 `supports_vision`/`is_multimodal` 已确认（全部正确）
- [x] google 所有模型的 `supports_vision`/`is_multimodal` 已确认（全部正确）
- [x] deepseek 所有模型的 `supports_vision`/`is_multimodal` 已确认（全部正确）
- [x] moonshot 所有模型的 `supports_vision`/`is_multimodal` 已确认（全部正确）
- [x] zhipu 所有模型的 `supports_vision`/`is_multimodal` 已确认（修正 glm-4）
- [x] 每个厂家至少有一个模型的 `supports_vision=True`（如果该厂家确实有视觉模型）

## 集成检查

- [x] 初始化定价后，模态数据正确填充到数据库
- [x] 前端价格表格完整渲染，7 个厂家的模型均显示模态列
- [x] 模态标签在不同屏幕尺寸下显示正常
- [x] 无 console 错误或 API 报错
