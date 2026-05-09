# Tasks

- [x] Task 1: 后端 — ModelPricing 表新增 `supports_vision` 和 `is_multimodal` 字段
  - 在 `backend/billing/models.py` 的 ModelPricing 类中添加两个列
  - 两个字段都是 `Boolean` 类型，默认 `False`
  - 由于 SQLite 无原生 ALTER TABLE ADD COLUMN，需通过 `alembic` 或 `create_all` + 数据迁移处理
  - 实现兼容性处理：检查列是否存在，不存在则添加

- [x] Task 2: 后端 — 初始化流程扩展，自动从 model_capabilities.json 回填模态数据
  - 修改 `backend/billing/pricing_manager.py` 的 `initialize_default_pricing()`
  - 创建 ModelPricing 记录后，从 `_model_capability_defaults` 查找 `supports_vision` 和 `is_multimodal`
  - 若找到匹配项则回填；若未找到则使用默认值 `False`
  - 确保现有记录可通过重新初始化补齐模态数据

- [x] Task 3: 后端 — `/billing/models` API 暴露模态字段
  - 修改 `backend/billing/routers/billing.py` 的 `get_models()` 响应构建
  - 每条 model 对象新增 `supports_vision` 和 `is_multimodal` 字段

- [x] Task 4: 前端 — `ModelPricing` 接口扩展
  - 修改 `frontend/src/features/billing/billingApi.ts`
  - 新增 `supports_vision: boolean` 和 `is_multimodal: boolean`

- [x] Task 5: 前端 — 价格表格新增"模态"列
  - 修改 `frontend/src/features/settings/SettingsPage.tsx`
  - 在`<th>模型</th>`后插入`<th>模态</th>`
  - 在模型名称`<td>`后插入模态标签`<td>`
  - 根据 `supports_vision` 和 `is_multimodal` 决定显示文本和样式

- [x] Task 6: 前端 — 模态标签样式
  - 修改 `frontend/src/features/settings/SettingsPage.module.css`
  - 新增 `.modality-badge` 基础样式（圆角、内边距、字体大小）
  - 新增 `.modality-text`（灰色）、`.modality-vision`（蓝色）、`.modality-multimodal`（紫色）
  - 标签应紧凑显示，不占用过多水平空间

- [x] Task 7: 数据 — alibaba(阿里通义千问) 模态数据确认
  - 逐条检查 `model_capabilities.json` 中所有 `provider: "alibaba"` 的条目
  - 根据 `阿里云百炼.md` 文档确认每个模型的真实模态能力
  - 修正 `supports_vision` 和 `is_multimodal` 值
  - **修正**：qwen-max (vision=true→false), qwen-max-2025-01-25 (vision=true→false)

- [x] Task 8: 数据 — openai 模态数据确认
  - **修正**：gpt-4.1 (vision=false→true), gpt-4.1-mini (vision=false→true), gpt-4.1-nano (vision=false→true)

- [x] Task 9: 数据 — anthropic 模态数据确认
  - 全部12个模型已正确，无修正

- [x] Task 10: 数据 — google 模态数据确认
  - 全部10个模型已正确，无修正

- [x] Task 11: 数据 — deepseek 模态数据确认
  - 全部10个模型已正确，无修正

- [x] Task 12: 数据 — moonshot(kimi) 模态数据确认
  - 全部3个模型已正确，无修正

- [x] Task 13: 数据 — zhipu(智谱AI) 模态数据确认
  - **修正**：glm-4 (vision=true→false, is_multimodal=true→false)

- [x] Task 14: 验证 — 运行 mypy 和 tsc 类型检查
  - `mypy backend/ --ignore-missing-imports`
  - `tsc --noEmit`（如果存在前端的 tsconfig）

## Task Dependencies

- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 3]（前端接口需与后端 API 响应一致）
- [Task 5] depends on [Task 4]
- [Task 6] depends on [Task 5]
- [Task 7] ~ [Task 13] 之间无依赖，可并行执行
- [Task 14] 最后执行，依赖所有任务
