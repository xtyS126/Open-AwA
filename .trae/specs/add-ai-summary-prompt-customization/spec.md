# Twitter Monitor 插件 AI 提示词自定义功能规范

## 为什么
当前 twitter-monitor 插件的 `summarize_twitter_tweets` 方法已经返回了完整的提示词信息，但这些提示词是硬编码在代码中的。用户希望能够通过配置自定义 AI 总结的提示词，以便根据不同需求调整总结风格和重点。

## 什么变化

### 新增功能

1. **配置化提示词**
   - 在 `schema.json` 中添加自定义提示词配置字段
   - 支持覆盖默认的总结角色、优先级规则、输出规则、语言规则
   - 支持自定义总结示例

2. **动态提示词生成**
   - `summarize_twitter_tweets` 方法优先使用配置的自定义提示词
   - 配置为空时回退到默认提示词
   - 保持向后兼容

3. **配置验证**
   - 添加配置验证逻辑，确保自定义提示词格式正确
   - 支持提示词模板变量

## 影响

- 受影响的文件：
  - `plugins/twitter-monitor/schema.json` - 添加配置字段
  - `plugins/twitter-monitor/src/index.py` - 修改提示词生成逻辑
  - 数据库中已安装插件的 config 字段

- 受影响的工具方法：
  - `summarize_twitter_tweets` - 支持自定义提示词

## 新增需求

### 需求：自定义 AI 总结提示词配置

系统应该支持通过插件配置自定义 AI 总结提示词，包括角色设定、优先级规则、输出规则、语言规则和示例。

#### 场景：使用默认提示词
- **条件**：用户未配置自定义提示词
- **行为**：使用代码中定义的默认提示词
- **结果**：summarize_twitter_tweets 返回完整的默认提示词和推文数据

#### 场景：使用自定义提示词
- **条件**：用户在配置中提供了自定义提示词
- **行为**：使用配置的自定义提示词覆盖默认提示词
- **结果**：summarize_twitter_tweets 返回自定义提示词和推文数据

#### 场景：部分自定义提示词
- **条件**：用户只配置了部分提示词字段
- **行为**：使用配置的值覆盖对应字段，其余使用默认值
- **结果**：返回混合了自定义和默认值的完整提示词

## 修改的需求

### 需求：summarize_twitter_tweets 方法返回完整提示词

#### 当前行为
- 方法返回硬编码的默认提示词和推文数据

#### 期望行为
- 方法优先使用配置中的自定义提示词
- 配置为空或缺失时使用默认提示词
- 保持返回结构不变，确保向后兼容

## 配置字段说明

### 新增配置字段（schema.json）

```json
{
  "summary_customization": {
    "type": "object",
    "title": "AI 总结提示词自定义",
    "description": "自定义 AI 总结时的提示词配置，不填则使用默认提示词",
    "properties": {
      "custom_summary_role": {
        "type": "string",
        "title": "自定义角色设定",
        "description": "AI 的角色定位，如：'你是一名 AI 行业速报编辑'"
      },
      "custom_priority_rules": {
        "type": "string",
        "title": "自定义优先级规则",
        "description": "按优先级列出需要关注的动态类型，每条规则占一行"
      },
      "custom_output_rules": {
        "type": "string",
        "title": "自定义输出规则",
        "description": "输出格式要求，每条规则占一行"
      },
      "custom_language_rules": {
        "type": "string",
        "title": "自定义语言规则",
        "description": "语言风格要求，每条规则占一行"
      },
      "custom_summary_example": {
        "type": "string",
        "title": "自定义总结示例",
        "description": "期望的输出示例，展示总结风格"
      },
      "enable_custom_summary": {
        "type": "boolean",
        "title": "启用自定义提示词",
        "default": false,
        "description": "是否启用自定义提示词，关闭时使用默认提示词"
      }
    }
  }
}
```

## 技术实现要点

1. **优先级策略**
   - 如果 `enable_custom_summary` 为 true 且配置了对应字段，使用配置值
   - 否则使用代码中的默认值

2. **配置读取**
   - 在 `TwitterMonitorPlugin` 类中读取 `summary_customization` 配置
   - 提供方法获取当前生效的提示词配置

3. **返回结构保持不变**
   - `summarize_twitter_tweets` 返回结构保持向后兼容
   - 新增字段标识提示词来源（custom 或 default）

4. **性能考虑**
   - 提示词生成在初始化时完成，避免重复计算
   - 配置变更时重新生成提示词
