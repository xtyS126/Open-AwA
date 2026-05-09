# 支持多厂商模型的思考深度参数 Spec

## Why
在前面的工作中，我们修复了 DeepSeek 思考模式的开关问题。但目前系统的“思考强度（Thinking Depth）”配置（前端滑动条 0-5 级）对各家厂商（包括最新的 GPT-5、Claude 4.7、Gemini 3、DeepSeek V4 等模型）支持不够精细。根据最新的 API 文档：
- **OpenAI (o1/o3/o4/gpt-5)** 支持 `reasoning_effort` (low/medium/high)。
- **Anthropic (Claude 4.6/4.7)** 废弃了 `budget_tokens`，改为 Adaptive Thinking (`thinking: {"type": "adaptive"}`) 配合 `output_config: {"effort": "low/medium/high/xhigh/max"}`。旧版 Claude (如 3.7) 继续使用 `budget_tokens`。
- **DeepSeek (V4/R1)** 支持 `thinking` 开关，同时 V4 系列支持通过 `reasoning_effort` 控制思考强度。
- **Gemini (2.5/3.0)** 支持通过 OpenAI 兼容接口传入 `reasoning_effort` (none/low/medium/high)。
- **智谱 (GLM-4.5/5)** 支持 `thinking` 开关，但不支持强度/预算控制。
- **阿里云 (Qwen/QwQ)** 支持 `enable_thinking`（通常通过 `extra_body` 传递）。
为了最大化发挥各模型特性，且不产生 API 兼容报错，需要针对不同模型制定专属的参数组装逻辑。

## What Changes
修改 `backend/core/model_service.py` 中的 `build_thinking_params` 函数，细化并适配所有支持思考模式的模型。

具体映射规则（基于 0-5 的深度值）：
1. **OpenAI (o1/o3/o4/gpt-5)**:
   - 深度 1 -> `low`, 2-3 -> `medium`, 4-5 -> `high`
   - 参数: `{"reasoning_effort": effort}`
2. **Anthropic**:
   - 如果是 Claude 4.6/4.7 系列（`claude-opus-4-6`, `claude-sonnet-4-6`, `claude-opus-4-7` 等）：
     - 深度 1 -> `low`, 2 -> `medium`, 3 -> `high`, 4 -> `xhigh`, 5 -> `max`
     - 参数: `{"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}`
   - 如果是旧版模型：
     - 参数: `{"thinking": {"type": "enabled", "budget_tokens": max(1024, depth * 4000)}}`
3. **DeepSeek (V系列/R1)**:
   - 如果明确关闭 (`thinking_enabled is False`) -> `{"extra_body": {"thinking": {"type": "disabled"}}}`
   - 否则开启 -> `{"extra_body": {"thinking": {"type": "enabled"}}}`，并且附加 `reasoning_effort`：
     - 深度 1-3 -> `high`, 4-5 -> `max`
4. **Gemini (2.5/3.0)**:
   - 如果明确关闭 -> `{"reasoning_effort": "none"}`
   - 深度 1 -> `low`, 2-3 -> `medium`, 4-5 -> `high`
   - 参数: `{"reasoning_effort": effort}`
5. **智谱 (GLM)**:
   - 明确关闭 -> `{"thinking": {"type": "disabled"}}`
   - 开启 -> `{"thinking": {"type": "enabled"}}`
6. **阿里云 (Qwen/QwQ)**:
   - 开启/关闭 -> `{"extra_body": {"enable_thinking": True/False}}`

## Impact
- Affected specs: 聊天发送时的思考参数生成逻辑
- Affected code: `backend/core/model_service.py`

## ADDED Requirements
### Requirement: Dynamic Thinking Parameters for All Major Providers
系统 SHALL 针对 GPT-5, Claude 4, Gemini 3, DeepSeek V4, Qwen 等不同模型输出对应合规的思考 API 参数。

#### Scenario: Claude 4.7 Adaptive Thinking
- **WHEN** provider is `anthropic` and model is `claude-opus-4-7` with depth 5
- **THEN** return `{"thinking": {"type": "adaptive"}, "output_config": {"effort": "max"}}`.

#### Scenario: Gemini 3 Reasoning Effort
- **WHEN** provider is `google` or model contains `gemini` and depth is 1
- **THEN** return `{"reasoning_effort": "low"}`.