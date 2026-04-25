# 计划：修改 AI 模型显示格式为 "供应商/模型名"

## 背景

当前项目中，AI 模型在下拉选择框中的显示格式不统一且不够直观。例如插件配置页显示为 `GPT-4 (openai/gpt-4)`，设置页显示为 `GPT-4 (openai)`。用户希望统一改为 `供应商/模型名` 格式（如 `OpenAI/gpt-4` 或 `OpenAI/GPT-4`）。

## 需要修改的文件

### 1. PluginConfigPage.tsx — 插件配置页的 ModelSelectorField

**文件**: `d:\代码\Open-AwA\frontend\src\features\plugins\PluginConfigPage.tsx`

**当前代码** (L333-L375):

```tsx
function ModelSelectorField(props) {
  // 只调用了 modelsAPI.getConfigurations() 获取模型配置列表
  const configs: ModelOption[] = (res.data.configurations || []).map((cfg) => ({
    config_id: cfg.id,
    display_name: cfg.display_name || cfg.model,
    provider: cfg.provider,
    model: cfg.model,
  }))
  // ...
  // 选项显示格式：{display_name} ({provider}/{model})
  // 例如: GPT-4 (openai/gpt-4)
}
```

**需要做的修改**:
1. 额外调用 `modelsAPI.getProviders()` 获取供应商目录，建立 `provider_id → provider_display_name` 映射字典
2. 将 `ModelOption` 扩展（或直接使用现有字段），将选项标签改为 `{provider_display_name} / {model}` 格式
3. 具体显示时，使用 `providerDisplayNameMap[opt.provider] || opt.provider` 来获取供应商显示名

**预期结果**: 选项从 "GPT-4 (openai/gpt-4)" → "OpenAI / gpt-4"（或 "OpenAI / GPT-4"）

### 2. SettingsPage.tsx — 设置页的 AI 参数配置选择框

**文件**: `d:\代码\Open-AwA\frontend\src\features\settings\SettingsPage.tsx`

**当前代码** (L1197-L1219 附近):

```tsx
<select value={selectedModelConfigId ?? ''} onChange={...}>
  {configurations.map(c => (
    <option key={c.id} value={c.id}>
      {c.display_name || c.model} ({c.provider})
    </option>
  ))}
</select>
// 显示格式：{display_name || model} ({provider})
// 例如: GPT-4 (openai)
```

**需要做的修改**:
1. 在该组件区域建立 provider 显示名映射（可能复用 SettingsPage 已有的 `loadGlobalModelOptions` 中的 provider 数据，或额外获取）
2. 将选项标签改为 `{provider_display_name} / {model}` 格式

**预期结果**: 选项从 "GPT-4 (openai)" → "OpenAI / gpt-4"

## 实现步骤

### Step 1: 修改 PluginConfigPage.tsx 的 ModelSelectorField

1. 在 `useEffect` 中，除了调用 `modelsAPI.getConfigurations()`，额外调用 `modelsAPI.getProviders()` 
2. 从 providers 响应中构建 `Record<string, string>` 字典：`{ "openai": "OpenAI", "deepseek": "DeepSeek", ... }`
3. 修改 `ModelOption` 的显示标签逻辑
4. 确保正确处理加载中/错误状态（provider 加载失败时回退使用 provider ID）

### Step 2: 修改 SettingsPage.tsx 的 AI 参数配置选择框

1. 确认该组件区域是否能获取到 provider 显示名映射（检查 SettingsPage 是否已有 provider 列表状态）
2. 若已有 provider 数据，直接复用构建映射
3. 若无，添加获取 providers 的逻辑
4. 修改选项标签为 `{provider_display_name} / {model}`

### Step 3: 验证

1. 确保 TypeScript 类型检查通过 (`tsc --noEmit`)
2. 确保插件配置页的模型选择下拉选项显示正确
3. 确保设置页的 AI 参数配置选择选项显示正确

## 注意点

- Provider ID 可能是小写（如 "openai", "deepseek", "qwen"），Provider 显示名是首字母大写（如 "OpenAI", "DeepSeek", "通义千问"）
- 当 provider 显示名获取失败时，应优雅回退到 provider ID
- 只在显示格式上做修改，不影响存储的值（仍存 `config_id`）
- 不改动模型管理表格（有独立列显示供应商和模型名，结构清晰无需改动）
