# 任务清单

## 任务 1：更新 schema.json 添加自定义提示词配置字段

- [x] 在 `plugins/twitter-monitor/schema.json` 中添加 `summary_customization` 配置对象
- [x] 配置包含以下字段：
  - [x] `custom_summary_role` (string) - 自定义角色设定
  - [x] `custom_priority_rules` (string) - 自定义优先级规则
  - [x] `custom_output_rules` (string) - 自定义输出规则
  - [x] `custom_language_rules` (string) - 自定义语言规则
  - [x] `custom_summary_example` (string) - 自定义总结示例
  - [x] `enable_custom_summary` (boolean) - 是否启用自定义提示词

## 任务 2：修改 TwitterMonitorPlugin 类支持自定义提示词

- [x] 在 `__init__` 方法中读取 `summary_customization` 配置
- [x] 添加 `_load_summary_customization` 方法解析自定义配置
- [x] 修改 `_refresh_config` 方法，包含自定义提示词配置
- [x] 添加 `_get_effective_summary_config` 方法返回生效的提示词配置
- [x] 修改 `summarize_twitter_tweets` 方法，使用生效的配置生成提示词

## 任务 3：确保向后兼容

- [x] 当 `enable_custom_summary` 为 false 或未配置时，使用默认提示词
- [x] 当自定义字段为空字符串时，使用对应默认字段
- [x] 返回结构保持不变，新增 `prompt_source` 字段标识来源

## 任务 4：测试验证

- [x] 编写单元测试验证默认提示词功能
- [x] 编写单元测试验证自定义提示词功能
- [x] 编写单元测试验证部分自定义场景
- [x] 测试配置变更后的提示词更新

## 任务依赖

- 任务 2 依赖于任务 1
- 任务 3 在任务 2 完成后进行
- 任务 4 在所有代码修改完成后进行
