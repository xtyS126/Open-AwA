# Tasks
- [x] Task 1: 完善 `build_thinking_params` 的模型适配逻辑
  - [x] SubTask 1.1: 拓展 OpenAI 逻辑，兼容 `gpt-5` 模型（使用 `reasoning_effort`）。
  - [x] SubTask 1.2: 更新 Anthropic 逻辑，对于 `claude-opus-4-6`、`claude-sonnet-4-6`、`claude-opus-4-7` 使用 `adaptive` thinking 并设置 `output_config.effort`；旧版本保持 `budget_tokens` 且最低 1024 限制。
  - [x] SubTask 1.3: 拓展 DeepSeek 逻辑，对于开启思考的情况，补充 `reasoning_effort` 的控制（深度 1-5 映射 low/medium/high/max）。
  - [x] SubTask 1.4: 增加 Google (Gemini) 逻辑，识别 `gemini` 模型，根据深度生成 `reasoning_effort`，关闭时返回 `none`。
  - [x] SubTask 1.5: 确保智谱和阿里云的开关逻辑保持正确，并在函数文档中说明各模型（GPT-5、Claude 4.7、Gemini 3 等）的参数特性。