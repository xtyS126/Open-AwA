# Tasks

- [ ] Task 1: 后端 `get_provider_catalog()` 合并 pricing_data.json 数据源
  - [ ] SubTask 1.1: 从 `config_loader.load_pricing_data()` 提取所有唯一 provider 并生成 fallback 条目
  - [ ] SubTask 1.2: 将 fallback 条目与数据库查询结果合并（数据库优先，JSON 补充）
  - [ ] SubTask 1.3: 每个 fallback 条目的 `selected_models` 取自 JSON 中该厂商的所有模型名
  - [ ] SubTask 1.4: fallback 条目标记 `source: "pricing_json"`，数据库条目标记 `source: "database"`

- [ ] Task 2: 前端"新增供应商"弹窗改造为下拉选择
  - [ ] SubTask 2.1: 新增 API 获取已知厂商列表（从 `/billing/providers` 已有数据的 `id` 提取）
  - [ ] SubTask 2.2: 将供应商标识输入框改为 `<select>` + 自定义选项
  - [ ] SubTask 2.3: 选择已知厂商后自动填充 display_name
  - [ ] SubTask 2.4: 保证自定义输入（非预置厂商）仍可正常创建

- [ ] Task 3: 验证计费配置页模型价格联动
  - [ ] SubTask 3.1: 确认 `initialize-pricing` 已将 JSON 数据导入 DB 后，计费 Tab 正确展示所有厂商
  - [ ] SubTask 3.2: 确认在未手动创建配置的情况下，计费 Tab 仍能展示 JSON 厂商及其模型（回退到 JSON 数据）
  - [ ] SubTask 3.3: 运行现有计费相关测试确保无回归

# Task Dependencies
- Task 2 依赖 Task 1（前端下拉列表需要后端 vendor list 数据）
- Task 3 依赖 Task 1（先确认后端合并逻辑正确）
- Task 2 与 Task 3 可并行
