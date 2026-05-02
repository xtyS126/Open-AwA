# Open-AwA 设置页 — 模型管理功能 开发文档

> **版本**: v1.0  
> **日期**: 2026-04-10  
> **状态**: 待评审  
> **适用分支**: `main`

---

## 目录

1. [功能需求说明](#1-功能需求说明)
2. [技术实现方案](#2-技术实现方案)
3. [数据库设计变更](#3-数据库设计变更)
4. [接口定义](#4-接口定义)
5. [前端交互流程](#5-前端交互流程)
6. [后端逻辑处理步骤](#6-后端逻辑处理步骤)
7. [第三方服务集成方案](#7-第三方服务集成方案)
8. [性能优化考虑](#8-性能优化考虑)
9. [安全防护措施](#9-安全防护措施)
10. [测试用例设计](#10-测试用例设计)
11. [部署上线计划](#11-部署上线计划)
12. [风险评估与应对方案](#12-风险评估与应对方案)

---

## 1. 功能需求说明

### 1.1 需求来源

基于手绘设计稿（见附图），需要在 Open-AwA 的 **设置页（Settings Page）** 中增强模型管理功能，包含以下核心模块：

### 1.2 设置页整体布局

设置页采用 **Tab 分页** 导航结构，包含以下 Tab：

| Tab 名称 | 说明 |
|---------|------|
| **模型（Model）** | 模型参数配置与切换 |
| **API** | API Provider 管理 |
| **提示词（Prompt）** | 系统提示词配置 |

### 1.3 模型参数配置功能点

#### 1.3.1 模型选择器（Model Selector）

- **功能描述**: 提供下拉菜单选择当前使用的 AI 模型
- **行为规则**:
  - 切换模型时，自动加载该模型对应的配置（温度、Top K、最大 Tokens 等参数）
  - 切换模型时，配置参数切换至该模型的存储值或默认值
  - 模型列表按 Provider 分组显示，支持按类型筛选

#### 1.3.2 温度（Temperature）控件

- **类型**: 滑块 + 数值输入框
- **默认值**: `0.7`
- **范围**: `0.0 ~ 2.0`
- **步长**: `0.1`
- **行为**: 若所选模型不支持温度调节，控件置灰不可操作

#### 1.3.3 Top K 控件

- **类型**: 数值输入框
- **默认值**: `0.9`（注：部分 Provider 将此参数映射为 Top P）
- **范围**: `0.0 ~ 1.0`
- **步长**: `0.1`
- **行为**: 若所选模型不支持 Top K/Top P，控件置灰不可操作

#### 1.3.4 最大 Tokens（Max Tokens）控件

- **类型**: 数值输入框
- **默认值**: 按模型规格自动匹配（例如 GPT-4 为 8192，DeepSeek 为 65536 等）
- **范围**: `1 ~ 模型最大上下文窗口`
- **行为**:
  - 默认值按照模型规格（context_window）自动对应到该模型的最大 Tokens 上限
  - 用户可自定义，但不超过模型支持的最大值
  - 切换模型时自动重置为新模型的默认值

#### 1.3.5 保存按钮

- 将当前模型配置（温度、Top K、最大 Tokens）持久化保存
- 保存后即时生效，下次对话使用新配置

### 1.4 模型管理列表（Model 管理表）

设计稿中展示了一个模型管理表格，结构如下：

| 列名 | 说明 |
|------|------|
| **图标** | 模型/Provider 的品牌图标 |
| **模型名** | 模型的显示名称 |
| **提供者（Provider）** | 模型所属服务商（OpenAI、Anthropic、DeepSeek 等） |
| **规格** | 模型规格参数（上下文窗口、是否支持函数调用等） |
| **图片** | 是否支持图片/视觉输入（多模态标识） |
| **多模（Multimodal）** | 是否为多模态模型 |
| **描述** | 模型功能描述 |
| **运行状态** | 当前模型可用性状态 |
| **删除** | 删除该模型配置 |

### 1.5 模型参数规则总结

| 规则项 | 说明 |
|--------|------|
| 切换模型时自动加载配置 | 模型选择器切换后，Temperature / Top K / Max Tokens 自动填充为该模型的存储值或默认值 |
| 不支持的参数置灰 | 若模型不支持某项调参（如温度），对应控件 disabled、灰色展示 |
| 参数默认值 | Temperature: `0.7`、Top K: `0.9`、Max Tokens: 按模型规格自动匹配 |
| 参数验证 | 不允许超出模型支持范围的值提交 |
| 配置关联 | 每个模型独立存储配置，互不影响 |

---

## 2. 技术实现方案

### 2.1 当前架构概览

```
┌──────────────────────────────────────────────────┐
│                    Frontend                       │
│   React 18 + TypeScript + Zustand + Vite          │
│   features/settings/SettingsPage.tsx               │
│   features/settings/modelsApi.ts                   │
│   shared/api/api.ts                                │
└──────────────────────┬───────────────────────────┘
                       │ HTTP / REST
┌──────────────────────▼───────────────────────────┐
│                    Backend                        │
│   FastAPI + SQLAlchemy + SQLite                   │
│   billing/routers/billing.py                      │
│   billing/pricing_manager.py                      │
│   billing/models.py (ModelConfiguration)           │
│   core/model_service.py                            │
└──────────────────────┬───────────────────────────┘
                       │ ORM
┌──────────────────────▼───────────────────────────┐
│                   Database                        │
│   SQLite: model_configurations 表                  │
│   SQLite: model_pricing 表                         │
└──────────────────────────────────────────────────┘
```

### 2.2 改造范围

#### 2.2.1 后端改造

| 模块 | 文件 | 改造内容 |
|------|------|---------|
| 数据模型 | `backend/billing/models.py` | `ModelConfiguration` 表新增 `temperature`, `top_k`, `top_p`, `max_tokens_limit`, `supports_temperature`, `supports_top_k`, `supports_vision`, `is_multimodal`, `model_spec`, `status` 等字段 |
| 定价管理 | `backend/billing/pricing_manager.py` | 新增模型能力查询方法、默认参数初始化逻辑、模型规格元数据管理 |
| API 路由 | `backend/billing/routers/billing.py` | 新增/修改模型配置 CRUD 接口，支持模型参数读写 |
| 模型服务 | `backend/core/model_service.py` | `build_provider_request()` 中读取模型配置的 temperature/top_k/max_tokens 参数 |
| Pydantic Schema | `backend/api/schemas.py` | 新增 `ModelConfigUpdateRequest`, `ModelCapabilities` 等 Schema |

#### 2.2.2 前端改造

| 模块 | 文件 | 改造内容 |
|------|------|---------|
| 设置页 | `frontend/src/features/settings/SettingsPage.tsx` | 重构 Model Tab，新增模型参数配置面板（Temperature 滑块、Top K 输入框、Max Tokens 输入框） |
| API 层 | `frontend/src/features/settings/modelsApi.ts` | 新增模型参数更新接口、模型能力查询接口 |
| 类型定义 | `frontend/src/features/settings/modelsApi.ts` | 扩展 `ModelConfiguration` 接口，增加参数字段与能力字段 |
| 样式 | `frontend/src/features/settings/SettingsPage.module.css` | 新增参数配置面板样式、滑块样式、禁用状态样式 |
| 聊天页 | `frontend/src/features/chat/ChatPage.tsx` | 模型选择器关联配置参数，发送消息时附带当前模型参数 |

### 2.3 技术选型

| 需求 | 技术方案 | 理由 |
|------|---------|------|
| 前端状态管理 | Zustand (已有) | 项目一致性，轻量高效 |
| 参数表单验证 | React 内置 + 自定义校验 | 避免引入额外表单库 |
| 滑块组件 | 原生 HTML `<input type="range">` + CSS | 无需引入新UI库 |
| 后端校验 | Pydantic v2 (已有) | FastAPI 原生集成 |
| 数据库迁移 | `migrate_db.py` (已有) | 项目已有的迁移工具 |

---

## 3. 数据库设计变更

### 3.1 `model_configurations` 表字段扩展

在现有 `ModelConfiguration` 模型基础上新增以下字段：

```sql
ALTER TABLE model_configurations ADD COLUMN temperature REAL DEFAULT 0.7;
ALTER TABLE model_configurations ADD COLUMN top_k REAL DEFAULT 0.9;
ALTER TABLE model_configurations ADD COLUMN top_p REAL DEFAULT NULL;
ALTER TABLE model_configurations ADD COLUMN max_tokens_limit INTEGER DEFAULT NULL;
ALTER TABLE model_configurations ADD COLUMN supports_temperature BOOLEAN DEFAULT 1;
ALTER TABLE model_configurations ADD COLUMN supports_top_k BOOLEAN DEFAULT 1;
ALTER TABLE model_configurations ADD COLUMN supports_vision BOOLEAN DEFAULT 0;
ALTER TABLE model_configurations ADD COLUMN is_multimodal BOOLEAN DEFAULT 0;
ALTER TABLE model_configurations ADD COLUMN model_spec TEXT DEFAULT NULL;
ALTER TABLE model_configurations ADD COLUMN status VARCHAR(20) DEFAULT 'active';
```

### 3.2 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `temperature` | REAL | 0.7 | 采样温度 |
| `top_k` | REAL | 0.9 | Top K 采样参数（可映射为 Top P） |
| `top_p` | REAL | NULL | Top P 参数（部分 Provider 使用） |
| `max_tokens_limit` | INTEGER | NULL | 用户自定义最大 Tokens，NULL 时使用模型默认值 |
| `supports_temperature` | BOOLEAN | TRUE | 模型是否支持温度调节 |
| `supports_top_k` | BOOLEAN | TRUE | 模型是否支持 Top K/Top P 调节 |
| `supports_vision` | BOOLEAN | FALSE | 是否支持视觉/图片输入 |
| `is_multimodal` | BOOLEAN | FALSE | 是否为多模态模型 |
| `model_spec` | TEXT (JSON) | NULL | 模型规格元数据（JSON 格式，含 context_window、function_calling 等） |
| `status` | VARCHAR(20) | 'active' | 模型运行状态: `active`, `inactive`, `error`, `deprecated` |

### 3.3 模型规格元数据 (`model_spec`) JSON 结构

```json
{
  "context_window": 128000,
  "max_output_tokens": 4096,
  "supports_function_calling": true,
  "supports_json_mode": true,
  "supports_streaming": true,
  "supports_vision": true,
  "supports_audio": false,
  "training_data_cutoff": "2024-04",
  "pricing_tier": "premium"
}
```

### 3.4 默认模型参数预置表

| Provider | 模型 | 默认 Temperature | 默认 Top K | 默认 Max Tokens | 支持温度 | 支持 Top K | 支持视觉 | 多模态 |
|----------|------|-----------------|-----------|----------------|---------|-----------|---------|--------|
| OpenAI | gpt-4o | 0.7 | 0.9 | 128000 | ✅ | ✅ | ✅ | ✅ |
| OpenAI | gpt-4o-mini | 0.7 | 0.9 | 128000 | ✅ | ✅ | ✅ | ✅ |
| OpenAI | gpt-3.5-turbo | 0.7 | 0.9 | 16385 | ✅ | ✅ | ❌ | ❌ |
| Anthropic | claude-3.5-sonnet | 0.7 | 0.9 | 200000 | ✅ | ✅ | ✅ | ✅ |
| Anthropic | claude-3-haiku | 0.7 | 0.9 | 200000 | ✅ | ✅ | ✅ | ✅ |
| DeepSeek | deepseek-chat | 0.7 | 0.9 | 65536 | ✅ | ✅ | ❌ | ❌ |
| DeepSeek | deepseek-reasoner | 0.7 | 0.9 | 65536 | ❌ | ❌ | ❌ | ❌ |
| Google | gemini-2.0-flash | 0.7 | 0.9 | 1048576 | ✅ | ✅ | ✅ | ✅ |
| Alibaba | qwen-plus | 0.7 | 0.9 | 131072 | ✅ | ✅ | ❌ | ❌ |
| Moonshot | moonshot-v1-128k | 0.7 | 0.9 | 128000 | ✅ | ✅ | ❌ | ❌ |
| Zhipu | glm-4 | 0.7 | 0.9 | 128000 | ✅ | ✅ | ✅ | ✅ |

### 3.5 迁移策略

- 使用项目已有的 `backend/migrate_db.py` 进行增量迁移
- 迁移脚本需检查列是否已存在（兼容重复执行）
- 迁移后执行默认参数初始化（对已有 `model_configurations` 记录填充默认值）

---

## 4. 接口定义

### 4.1 模型配置参数更新

**`PUT /api/billing/configurations/{config_id}/parameters`**

更新指定模型配置的运行参数。

**Request Body:**

```json
{
  "temperature": 0.7,
  "top_k": 0.9,
  "top_p": null,
  "max_tokens_limit": 4096
}
```

**Response (200):**

```json
{
  "success": true,
  "configuration": {
    "id": 1,
    "provider": "openai",
    "model": "gpt-4o",
    "temperature": 0.7,
    "top_k": 0.9,
    "top_p": null,
    "max_tokens_limit": 4096,
    "supports_temperature": true,
    "supports_top_k": true,
    "updated_at": "2026-04-10T12:00:00Z"
  }
}
```

**Validation Rules:**

| 字段 | 类型 | 约束 |
|------|------|------|
| temperature | float \| null | 0.0 ≤ val ≤ 2.0 |
| top_k | float \| null | 0.0 ≤ val ≤ 1.0 |
| top_p | float \| null | 0.0 ≤ val ≤ 1.0 |
| max_tokens_limit | int \| null | 1 ≤ val ≤ model_spec.context_window |

---

### 4.2 获取模型能力与默认参数

**`GET /api/billing/configurations/{config_id}/capabilities`**

**Response (200):**

```json
{
  "config_id": 1,
  "provider": "openai",
  "model": "gpt-4o",
  "capabilities": {
    "supports_temperature": true,
    "supports_top_k": true,
    "supports_vision": true,
    "is_multimodal": true,
    "supports_function_calling": true,
    "supports_streaming": true
  },
  "defaults": {
    "temperature": 0.7,
    "top_k": 0.9,
    "max_tokens": 128000
  },
  "limits": {
    "temperature_min": 0.0,
    "temperature_max": 2.0,
    "top_k_min": 0.0,
    "top_k_max": 1.0,
    "max_tokens_min": 1,
    "max_tokens_max": 128000
  }
}
```

---

### 4.3 获取模型管理列表（扩展）

**`GET /api/billing/configurations`**

在现有返回基础上扩展，每个 configuration 对象增加以下字段：

```json
{
  "configurations": [
    {
      "id": 1,
      "provider": "openai",
      "model": "gpt-4o",
      "display_name": "GPT-4o",
      "description": "OpenAI 最新多模态模型",
      "icon": "openai",
      "temperature": 0.7,
      "top_k": 0.9,
      "max_tokens": 128000,
      "max_tokens_limit": null,
      "supports_temperature": true,
      "supports_top_k": true,
      "supports_vision": true,
      "is_multimodal": true,
      "model_spec": {
        "context_window": 128000,
        "max_output_tokens": 4096,
        "supports_function_calling": true
      },
      "status": "active",
      "is_default": true,
      "is_active": true,
      "created_at": "2026-04-01T00:00:00Z",
      "updated_at": "2026-04-10T12:00:00Z"
    }
  ]
}
```

---

### 4.4 批量更新模型状态

**`PUT /api/billing/configurations/batch-status`**

```json
{
  "config_ids": [1, 2, 3],
  "status": "inactive"
}
```

**Response (200):**

```json
{
  "success": true,
  "updated_count": 3
}
```

---

### 4.5 模型参数重置为默认值

**`POST /api/billing/configurations/{config_id}/reset-parameters`**

将指定模型的 temperature、top_k、max_tokens_limit 重置为系统默认值。

**Response (200):**

```json
{
  "success": true,
  "configuration": {
    "id": 1,
    "temperature": 0.7,
    "top_k": 0.9,
    "max_tokens_limit": null
  }
}
```

---

### 4.6 聊天接口参数透传

现有 `POST /api/chat` 接口的请求体扩展，支持可选的模型参数覆盖：

```json
{
  "message": "你好",
  "session_id": "abc123",
  "provider": "openai",
  "model": "gpt-4o",
  "mode": "stream",
  "parameters": {
    "temperature": 0.5,
    "top_k": 0.8,
    "max_tokens": 2048
  }
}
```

> 若 `parameters` 为空或不传，则使用该模型在 `model_configurations` 表中存储的配置值。

---

## 5. 前端交互流程

### 5.1 设置页模型 Tab 交互流程

```
用户进入设置页
    │
    ▼
加载 Tab 列表 [模型 | API | 提示词]
    │
    ▼ 点击"模型"Tab
    │
┌───▼────────────────────────────────────────────────┐
│  ① 加载模型配置列表 GET /api/billing/configurations │
│  ② 加载模型管理表格数据                              │
│  ③ 默认选中 is_default=true 的模型                    │
└───┬────────────────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────────────────────┐
│  显示模型参数配置面板:                               │
│  ┌─────────────────────────────────────────┐       │
│  │ 模型选择器: [GPT-4o ▼]                   │       │
│  │ 温度:      [===●=======] 0.7             │       │
│  │ Top K:     [0.9        ]                 │       │
│  │ 最大Tokens: [128000     ]                │       │
│  │            [保存]                        │       │
│  └─────────────────────────────────────────┘       │
│                                                    │
│  模型管理表格:                                      │
│  ┌──────┬────────┬─────┬────┬────┬────┬─────┬────┐ │
│  │ 图标 │ 模型名 │提供者│规格│图片│多模│运行态│删除│ │
│  ├──────┼────────┼─────┼────┼────┼────┼─────┼────┤ │
│  │ 🟢   │ GPT-4o │OpenAI│128K│ ✅ │ ✅ │active│ 🗑│ │
│  │ 🔵   │ Claude │Anthr.│200K│ ✅ │ ✅ │active│ 🗑│ │
│  │ 🟣   │ DeepSk │DeepS.│ 64K│ ❌ │ ❌ │active│ 🗑│ │
│  └──────┴────────┴─────┴────┴────┴────┴─────┴────┘ │
└────────────────────────────────────────────────────┘
```

### 5.2 模型切换交互流程

```
用户在模型选择器中切换模型
    │
    ▼
GET /api/billing/configurations/{config_id}/capabilities
    │
    ▼
┌─────────────────────────────────────────────┐
│ 判断模型能力:                                │
│ ├─ supports_temperature == false?            │
│ │   → 温度滑块 disabled, 显示灰色            │
│ ├─ supports_top_k == false?                  │
│ │   → Top K 输入框 disabled, 显示灰色        │
│ └─ 获取模型默认值/用户保存值                   │
│     → 填充 temperature, top_k, max_tokens    │
└─────────────────────────────────────────────┘
    │
    ▼
UI 更新: 参数面板展示新模型的配置
```

### 5.3 保存配置交互流程

```
用户修改参数 → 点击"保存"按钮
    │
    ▼
前端校验:
  ├─ temperature: 0.0 ~ 2.0
  ├─ top_k: 0.0 ~ 1.0
  └─ max_tokens: 1 ~ model.context_window
    │
    ▼ 校验通过
PUT /api/billing/configurations/{config_id}/parameters
    │
    ├─ 成功 → 显示 "保存成功" 提示，更新本地状态
    └─ 失败 → 显示错误信息，不修改本地状态
```

### 5.4 前端组件结构设计

```
SettingsPage
├── TabNav [模型 | API | 提示词 | ...]
│
├── ModelTab (新增组件)
│   ├── ModelSelector            // 模型选择下拉框
│   ├── ModelParameterPanel      // 参数配置面板
│   │   ├── TemperatureSlider    // 温度滑块
│   │   ├── TopKInput            // Top K 输入框
│   │   ├── MaxTokensInput       // 最大 Tokens 输入框
│   │   └── SaveButton           // 保存按钮
│   └── ModelManagementTable     // 模型管理表格
│       ├── ModelRow             // 每行模型信息
│       │   ├── ModelIcon        // 模型图标
│       │   ├── ModelCapBadges   // 能力标签(视觉/多模态)
│       │   ├── StatusIndicator  // 运行状态指示
│       │   └── DeleteButton     // 删除按钮
│       └── Pagination           // 分页(如模型数量较多)
│
├── APITab (现有)
└── PromptTab (现有)
```

### 5.5 前端状态管理设计

建议新增 Zustand store 或在现有 settings 模块中扩展：

```typescript
interface ModelSettingsState {
  // 当前选中模型
  selectedConfigId: number | null
  selectedConfig: ModelConfiguration | null

  // 模型参数（编辑中的值）
  editingParams: {
    temperature: number
    top_k: number
    max_tokens_limit: number | null
  }

  // 模型能力信息
  capabilities: ModelCapabilities | null

  // 所有模型配置列表
  configurations: ModelConfiguration[]

  // 操作
  loadConfigurations: () => Promise<void>
  selectModel: (configId: number) => Promise<void>
  updateParams: (params: Partial<EditingParams>) => void
  saveParams: () => Promise<void>
  resetParams: () => Promise<void>
  deleteConfiguration: (configId: number) => Promise<void>
}
```

---

## 6. 后端逻辑处理步骤

### 6.1 模型参数更新流程

```
接收 PUT /api/billing/configurations/{config_id}/parameters
    │
    ▼
① 身份验证 (get_current_user)
    │
    ▼
② 查询 ModelConfiguration by config_id
    ├─ 未找到 → 返回 404
    └─ 找到 → 继续
    │
    ▼
③ 参数校验 (Pydantic)
    ├─ temperature: Optional[float], ge=0.0, le=2.0
    ├─ top_k: Optional[float], ge=0.0, le=1.0
    ├─ top_p: Optional[float], ge=0.0, le=1.0
    └─ max_tokens_limit: Optional[int], ge=1
    │
    ▼
④ 业务规则校验
    ├─ 若 supports_temperature == false 且传入了 temperature → 忽略或返回警告
    ├─ 若 supports_top_k == false 且传入了 top_k → 忽略或返回警告
    └─ 若 max_tokens_limit > model_spec.context_window → 返回 422 校验失败
    │
    ▼
⑤ 更新数据库
    ├─ 只更新传入的非 None 字段
    └─ 自动更新 updated_at
    │
    ▼
⑥ 返回更新后的完整配置
```

### 6.2 模型切换时配置加载流程

```
接收 GET /api/billing/configurations/{config_id}/capabilities
    │
    ▼
① 查询 ModelConfiguration
    │
    ▼
② 组装能力信息
    ├─ 从 ModelConfiguration 字段读取: supports_temperature, supports_top_k, supports_vision, is_multimodal
    └─ 从 model_spec JSON 解析: context_window, supports_function_calling 等
    │
    ▼
③ 组装默认值与限制范围
    ├─ defaults: { temperature, top_k, max_tokens (来自 context_window) }
    └─ limits: { *_min, *_max 由模型规格决定 }
    │
    ▼
④ 返回 capabilities + defaults + limits
```

### 6.3 聊天接口参数透传流程

```
接收 POST /api/chat (含 parameters 字段)
    │
    ▼
① 解析 parameters
    ├─ 若 parameters 存在 → 使用请求中的参数
    └─ 若 parameters 为空 → 查询 ModelConfiguration 获取存储值
    │
    ▼
② 传递参数给 AIAgent
    │
    ▼
③ AIAgent → ExecutionLayer → model_service.build_provider_request()
    │
    ▼
④ build_provider_request() 中:
    ├─ OpenAI/DeepSeek/Moonshot/Zhipu/Alibaba:
    │   payload["temperature"] = temperature
    │   payload["top_p"] = top_k (映射)
    │   payload["max_tokens"] = max_tokens_limit or default
    │
    └─ Anthropic:
        payload["temperature"] = temperature
        payload["top_k"] = top_k
        payload["max_tokens"] = max_tokens_limit or default
```

### 6.4 模型默认参数初始化

在 `PricingManager.initialize_default_pricing()` 扩展：

```python
def initialize_model_defaults(self):
    """
    为已有的 ModelConfiguration 记录填充默认参数。
    仅在字段为 NULL 时更新，不覆盖用户已自定义的值。
    """
    MODEL_DEFAULTS = {
        ("openai", "gpt-4o"): {
            "temperature": 0.7, "top_k": 0.9,
            "supports_temperature": True, "supports_top_k": True,
            "supports_vision": True, "is_multimodal": True,
            "model_spec": {"context_window": 128000, "max_output_tokens": 4096}
        },
        ("deepseek", "deepseek-reasoner"): {
            "temperature": 0.7, "top_k": 0.9,
            "supports_temperature": False, "supports_top_k": False,
            "supports_vision": False, "is_multimodal": False,
            "model_spec": {"context_window": 65536}
        },
        # ... 更多模型
    }
    # 遍历已有配置，填充默认值
```

---

## 7. 第三方服务集成方案

### 7.1 现有 Provider 集成状态

| Provider | API 端点 | 认证方式 | Temperature | Top K/P | 视觉 | 备注 |
|----------|---------|---------|------------|---------|------|------|
| OpenAI | `api.openai.com/v1/chat/completions` | Bearer Token | ✅ `temperature` | ✅ `top_p` | ✅ | 使用 top_p 而非 top_k |
| Anthropic | `api.anthropic.com/v1/messages` | `x-api-key` Header | ✅ `temperature` | ✅ `top_k` | ✅ | 使用原生 top_k |
| DeepSeek | `api.deepseek.com/v1/chat/completions` | Bearer Token | ✅ `temperature` | ✅ `top_p` | ❌ | deepseek-reasoner 不支持温度 |
| Google | `generativelanguage.googleapis.com/v1beta` | API Key (query) | ✅ `temperature` | ✅ `topK` + `topP` | ✅ | 参数名称不同 |
| Alibaba | `dashscope.aliyuncs.com/compatible-mode/v1` | Bearer Token | ✅ `temperature` | ✅ `top_p` | 部分 | 兼容 OpenAI 格式 |
| Moonshot | `api.moonshot.cn/v1/chat/completions` | Bearer Token | ✅ `temperature` | ✅ `top_p` | ❌ | 兼容 OpenAI 格式 |
| Zhipu | `open.bigmodel.cn/api/paas/v4/chat/completions` | Bearer Token | ✅ `temperature` | ✅ `top_p` | 部分 | 兼容 OpenAI 格式 |

### 7.2 参数映射规则

在 `build_provider_request()` 中需要根据 Provider 执行参数名称映射：

```python
PROVIDER_PARAM_MAPPING = {
    "openai":    {"temperature": "temperature", "top_k": "top_p", "max_tokens": "max_tokens"},
    "anthropic": {"temperature": "temperature", "top_k": "top_k", "max_tokens": "max_tokens"},
    "deepseek":  {"temperature": "temperature", "top_k": "top_p", "max_tokens": "max_tokens"},
    "google":    {"temperature": "temperature", "top_k": "topK", "max_tokens": "maxOutputTokens"},
    "alibaba":   {"temperature": "temperature", "top_k": "top_p", "max_tokens": "max_tokens"},
    "moonshot":  {"temperature": "temperature", "top_k": "top_p", "max_tokens": "max_tokens"},
    "zhipu":     {"temperature": "temperature", "top_k": "top_p", "max_tokens": "max_tokens"},
}
```

### 7.3 Google Provider 特殊处理

Google Gemini API 的参数结构与 OpenAI 格式不同，需要特殊适配：

```json
{
  "contents": [...],
  "generationConfig": {
    "temperature": 0.7,
    "topK": 40,
    "topP": 0.9,
    "maxOutputTokens": 2048
  }
}
```

> **注意**: Google 的 `topK` 是整数（范围 1-40，参见 [Google GenerationConfig 文档](https://ai.google.dev/api/rest/v1beta/GenerationConfig)），与其他 Provider 的浮点数 `top_p`（0.0-1.0）不同。映射规则应在 `PROVIDER_PARAM_MAPPING` 常量中统一维护，当 Google API 规格变更时只需更新该配置。转换公式: `google_topK = round(top_k * 40)`，其中 `top_k` 为归一化的 0.0-1.0 浮点数。

---

## 8. 性能优化考虑

### 8.1 前端性能优化

| 优化点 | 方案 | 预期收益 |
|--------|------|---------|
| 模型配置缓存 | 首次加载后缓存到 Zustand store，切换 Tab 时不重新请求 | 减少 API 调用，提升切换速度 |
| 模型能力缓存 | 缓存每个 config_id 的 capabilities 信息，有效期 5 分钟 | 避免切换模型时重复请求 |
| 参数更新防抖 | 滑块拖动时使用 `debounce(300ms)` 延迟更新 UI 数值显示 | 避免高频重渲染 |
| 保存请求节流 | 保存按钮点击后 2s 内禁用，防止重复提交 | 防止重复写入 |
| 组件懒加载 | ModelManagementTable 使用 `React.lazy()` | 减小首屏加载体积 |

### 8.2 后端性能优化

| 优化点 | 方案 | 预期收益 |
|--------|------|---------|
| 配置查询缓存 | 使用 `functools.lru_cache` 或内存字典缓存热点模型配置，TTL 60s | 减少数据库查询 |
| 批量查询优化 | `GET /configurations` 接口使用 `joinedload` 避免 N+1 查询 | 减少数据库往返 |
| 异步数据库操作 | 对模型配置读写使用 `asyncio.to_thread()` 包装同步 SQLAlchemy 调用 | 避免事件循环阻塞 |
| 索引优化 | `model_configurations` 表在 `(provider, model, is_active)` 上建立复合索引 | 加速过滤查询 |
| 参数校验前置 | Pydantic Schema 在路由层完成校验，减少数据库无效写入 | 减少无效操作 |

### 8.3 数据库性能优化

```sql
-- 复合索引: 加速按 Provider 和状态过滤
CREATE INDEX IF NOT EXISTS idx_model_config_provider_active 
  ON model_configurations(provider, is_active);

-- 索引: 加速默认模型查找
CREATE INDEX IF NOT EXISTS idx_model_config_default 
  ON model_configurations(is_default) WHERE is_default = 1;
```

---

## 9. 安全防护措施

### 9.1 输入校验

| 字段 | 校验规则 | 防御目标 |
|------|---------|---------|
| temperature | float, 0.0-2.0, 精度 0.01 | 防止参数越界导致异常 API 调用 |
| top_k | float, 0.0-1.0, 精度 0.01 | 防止参数越界 |
| max_tokens_limit | int, 1 至模型上限 | 防止超大值导致高额费用 |
| config_id | int, 正整数 | 防止注入攻击 |
| model_spec | JSON Schema 校验 | 防止非法 JSON 注入 |

### 9.2 权限控制

| 操作 | 权限要求 | 说明 |
|------|---------|------|
| 查看模型配置 | 登录用户 | 所有已认证用户可查看 |
| 修改模型参数 | 登录用户 | 用户修改自己使用的模型参数 |
| 删除模型配置 | 管理员 | 仅 `role=admin` 的用户可删除 |
| 批量状态更新 | 管理员 | 仅管理员可批量操作 |
| API Key 查看 | 管理员 | API Key 仅管理员可见完整内容 |

### 9.3 API Key 安全

- API Key 存储时使用加密存储（建议使用 `cryptography.fernet` 对称加密）
- 非管理员查询时，`api_key` 字段返回掩码值（如 `sk-****...****3a7b`）
- 审计日志记录所有 API Key 的创建、修改、删除操作
- 前端传输 API Key 时确保使用 HTTPS

### 9.4 费用安全

- `max_tokens_limit` 与 `BudgetConfig` 联动：当用户设置的 max_tokens 可能导致超出预算时，返回警告信息
- 每次对话前检查当前预算余额，不足时拒绝请求
- 异常高频参数修改（如 1 分钟内修改超过 10 次）触发限流

### 9.5 日志与审计

- 所有模型参数修改操作记录到 `audit_logs` 表
- 日志包含：操作用户、操作时间、修改前后的参数值、请求 IP
- 敏感字段（API Key）在日志中自动脱敏（已有 `config/logging.py` 脱敏机制）

---

## 10. 测试用例设计

### 10.1 单元测试（Backend - pytest）

#### 10.1.1 数据库模型测试

```python
class TestModelConfigurationFields:
    """测试 ModelConfiguration 新增字段"""

    def test_default_temperature(self):
        """温度默认值应为 0.7"""

    def test_default_top_k(self):
        """Top K 默认值应为 0.9"""

    def test_model_spec_json_serialization(self):
        """model_spec JSON 字段应正确序列化和反序列化"""

    def test_status_default_active(self):
        """status 默认值应为 'active'"""

    def test_supports_flags_default_true(self):
        """supports_temperature/supports_top_k 默认值应为 True"""
```

#### 10.1.2 参数校验测试

```python
class TestParameterValidation:
    """测试参数校验逻辑"""

    def test_temperature_valid_range(self):
        """温度在 0.0-2.0 范围内应通过校验"""

    def test_temperature_out_of_range(self):
        """温度超出范围应返回 422"""

    def test_top_k_valid_range(self):
        """Top K 在 0.0-1.0 范围内应通过校验"""

    def test_max_tokens_exceeds_model_limit(self):
        """max_tokens 超过模型上限应返回 422"""

    def test_unsupported_parameter_ignored(self):
        """模型不支持的参数修改应被忽略"""
```

#### 10.1.3 API 接口测试

```python
class TestParameterUpdateAPI:
    """测试参数更新 API"""

    def test_update_temperature_success(self):
        """更新温度参数应返回 200"""

    def test_update_nonexistent_config(self):
        """更新不存在的配置应返回 404"""

    def test_update_without_auth(self):
        """未认证请求应返回 401"""

    def test_capabilities_response_format(self):
        """capabilities 接口返回格式应符合规范"""

    def test_batch_status_update(self):
        """批量状态更新应正确修改多条记录"""

    def test_reset_parameters(self):
        """重置参数应恢复为系统默认值"""
```

#### 10.1.4 Provider 参数映射测试

```python
class TestProviderParameterMapping:
    """测试不同 Provider 的参数映射"""

    def test_openai_uses_top_p(self):
        """OpenAI 应将 top_k 映射为 top_p"""

    def test_anthropic_uses_top_k(self):
        """Anthropic 应使用原生 top_k"""

    def test_google_uses_topK_integer(self):
        """Google 应将 top_k 映射为整数 topK"""

    def test_deepseek_reasoner_no_temperature(self):
        """DeepSeek Reasoner 请求中不应包含 temperature"""
```

### 10.2 前端测试（Vitest）

#### 10.2.1 组件测试

```typescript
describe('TemperatureSlider', () => {
  it('应渲染滑块控件', () => {})
  it('拖动滑块应更新温度值', () => {})
  it('不支持温度的模型应禁用滑块', () => {})
  it('温度值应限制在 0-2 范围', () => {})
})

describe('TopKInput', () => {
  it('应渲染数值输入框', () => {})
  it('输入值应限制在 0-1 范围', () => {})
  it('不支持的模型应禁用输入框', () => {})
})

describe('MaxTokensInput', () => {
  it('应显示模型默认最大 Tokens', () => {})
  it('输入值不应超过模型上限', () => {})
  it('切换模型应重置为新模型默认值', () => {})
})

describe('ModelSelector', () => {
  it('应加载模型列表', () => {})
  it('切换模型应触发参数加载', () => {})
  it('应标记默认模型', () => {})
})
```

#### 10.2.2 集成测试

```typescript
describe('ModelTab Integration', () => {
  it('切换模型应联动更新所有参数控件', () => {})
  it('保存参数应调用后端 API 并显示成功提示', () => {})
  it('保存失败应显示错误提示且不修改本地状态', () => {})
  it('不支持的参数控件应置灰', () => {})
})
```

### 10.3 E2E 测试（Playwright）

```typescript
test.describe('设置页模型管理', () => {
  test('进入设置页应显示模型 Tab', async ({ page }) => {
    await page.goto('/settings?tab=models')
    await expect(page.locator('[data-testid="model-selector"]')).toBeVisible()
  })

  test('切换模型应更新参数面板', async ({ page }) => {
    // 选择不同模型，验证参数面板更新
  })

  test('保存参数应持久化', async ({ page }) => {
    // 修改温度 → 保存 → 刷新页面 → 验证温度值
  })

  test('不支持温度的模型应禁用温度控件', async ({ page }) => {
    // 选择 DeepSeek Reasoner → 验证温度滑块 disabled
  })

  test('模型管理表格应展示正确信息', async ({ page }) => {
    // 验证表格列、数据正确性
  })
})
```

---

## 11. 部署上线计划

### 11.1 里程碑规划

| 阶段 | 内容 | 交付物 |
|------|------|--------|
| **Phase 1: 数据库迁移** | 新增字段、索引、默认数据初始化 | 迁移脚本、默认参数配置 |
| **Phase 2: 后端 API** | 参数 CRUD 接口、能力查询接口、参数映射逻辑 | API 端点、Pydantic Schema |
| **Phase 3: 前端 UI** | 模型参数面板、模型管理表格、交互逻辑 | React 组件、CSS 样式 |
| **Phase 4: 集成联调** | 前后端联调、聊天参数透传 | 联调通过 |
| **Phase 5: 测试验收** | 单元测试、集成测试、E2E 测试 | 测试报告 |
| **Phase 6: 上线发布** | 灰度发布、监控、回滚准备 | 发布包 |

### 11.2 部署步骤

```
1. 数据库迁移
   ├─ 备份当前 SQLite 数据库 (openawa.db)
   ├─ 执行 ALTER TABLE 增加新字段
   ├─ 执行默认数据初始化脚本
   └─ 验证迁移结果 (字段存在性、默认值正确性)

2. 后端部署
   ├─ 更新 requirements.txt (如有新依赖)
   ├─ 部署新版本后端代码
   ├─ 重启 FastAPI 服务
   └─ 健康检查 GET /health

3. 前端部署
   ├─ npm run build (TypeScript 检查 + Vite 构建)
   ├─ 部署构建产物
   └─ 验证页面加载正常

4. 功能验证
   ├─ 设置页 → 模型 Tab → 模型选择 → 参数配置 → 保存
   ├─ 对话页 → 使用配置的参数进行对话
   └─ 验证不同 Provider 的参数映射正确
```

### 11.3 灰度发布方案

利用已有的 `FeatureFlagManager`：

```python
# 在 feature_flags.py 中添加特性标志
feature_flag_manager.set_rule("model_parameter_config", FeatureRule(
    enabled=True,
    rollout_percentage=10,  # 先 10% 用户可见
    allow_accounts=["admin_account"],  # 管理员账号始终可见
))
```

### 11.4 回滚方案

| 场景 | 回滚操作 |
|------|---------|
| 数据库迁移失败 | 从备份恢复 SQLite 文件 |
| 后端 API 异常 | 回滚到上一版本后端代码，重启服务 |
| 前端界面异常 | 回滚到上一版本前端构建产物 |
| 数据不一致 | 执行修复脚本，将新字段重置为默认值 |

---

## 12. 风险评估与应对方案

### 12.1 风险矩阵

| 风险 | 可能性 | 影响 | 等级 | 应对方案 |
|------|--------|------|------|---------|
| 数据库迁移导致数据丢失 | 低 | 高 | 🟡 中 | 迁移前备份数据库；ALTER TABLE 仅增加字段不删除 |
| 不同 Provider 参数格式不兼容 | 中 | 中 | 🟡 中 | 建立参数映射表，每个 Provider 独立适配与测试 |
| 用户设置极端参数导致高费用 | 中 | 高 | 🔴 高 | max_tokens 限制在模型上限内；与 Budget 联动；前端警告提示 |
| 模型不支持的参数传递导致 API 报错 | 中 | 中 | 🟡 中 | 后端发送前过滤不支持的参数；前端 disabled 控件 |
| 前端状态不一致（缓存与后端不同步） | 中 | 低 | 🟢 低 | 每次打开设置页强制刷新配置；保存后更新本地 store |
| SQLite 并发写入冲突 | 低 | 中 | 🟢 低 | 现有连接池已处理（pool_size=5）；写操作使用事务 |
| 第三方 Provider API 变更 | 低 | 高 | 🟡 中 | 参数映射表可配置化；监控 Provider API 版本；定期回归测试 |
| Google Provider topK 整数转换精度问题 | 中 | 低 | 🟢 低 | Google 使用独立映射函数，浮点数 → 整数转换使用 `round()` |
| 用户同时在多设备修改同一模型配置 | 低 | 低 | 🟢 低 | 使用 `updated_at` 乐观锁，检测冲突时提示刷新 |

### 12.2 关键技术难点

#### 难点 1: DeepSeek Reasoner 等特殊模型的参数处理

**问题**: `deepseek-reasoner` 不支持 temperature 和 top_p 参数，传递这些参数会导致 API 报错。

**解决方案**:
- 数据库中通过 `supports_temperature=false`, `supports_top_k=false` 标记
- `build_provider_request()` 中根据模型能力过滤参数
- 前端根据 capabilities 禁用对应控件

#### 难点 2: 现有同步数据库调用在异步函数中的问题

**问题**: 项目中存在同步 SQLAlchemy `.query()` 在 `async def` 路由中直接调用的模式，会阻塞事件循环。

**解决方案**:
- 新增的接口使用 `sync def` 路由处理函数（FastAPI 自动在线程池中执行）
- 或者使用 `asyncio.to_thread()` 包装同步数据库操作
- 保持与项目现有模式一致
- **技术债务追踪**: 现有代码中 `memory/manager.py`、`memory/experience_manager.py`、`api/routes/auth.py`、`security/audit.py` 均存在同步 `.query()` 在 `async def` 中直接调用的问题（阻塞事件循环），本次新增接口应避免引入同类问题，并建议后续统一治理（参见已知问题清单）

#### 难点 3: 模型规格元数据的维护

**问题**: 不同 Provider 的模型规格（context_window、能力标志等）需要持续更新维护。

**解决方案**:
- `model_spec` 使用 JSON 字段灵活存储
- 在 `PricingManager.initialize_default_pricing()` 中维护默认规格
- 管理员可通过 API 手动更新特定模型的规格信息
- 未来可考虑从 Provider API 自动获取模型列表与能力信息

### 12.3 兼容性考虑

| 场景 | 兼容策略 |
|------|---------|
| 旧版前端访问新后端 | `GET /configurations` 接口向后兼容，新字段为可选 |
| 新版前端访问旧后端 | 前端做降级处理，新字段不存在时使用默认值 |
| 已有配置无新字段 | 迁移脚本填充默认值；`serialize_configuration()` 中对 None 值提供默认 |
| 聊天 API 无 parameters | 保持现有行为不变，从配置表读取 |

---

## 附录

### A. 相关文件清单

| 文件 | 类型 | 改动性质 |
|------|------|---------|
| `backend/billing/models.py` | 后端模型 | 修改：新增字段 |
| `backend/billing/routers/billing.py` | 后端路由 | 修改：新增 API 端点 |
| `backend/billing/pricing_manager.py` | 后端服务 | 修改：新增方法 |
| `backend/core/model_service.py` | 后端服务 | 修改：参数映射逻辑 |
| `backend/api/schemas.py` | 后端模型 | 修改：新增 Schema |
| `backend/api/routes/chat.py` | 后端路由 | 修改：参数透传 |
| `backend/migrate_db.py` | 迁移工具 | 修改：新增迁移逻辑 |
| `frontend/src/features/settings/SettingsPage.tsx` | 前端页面 | 修改：重构 Model Tab |
| `frontend/src/features/settings/modelsApi.ts` | 前端 API | 修改：新增接口 |
| `frontend/src/features/settings/SettingsPage.module.css` | 前端样式 | 修改：新增样式 |
| `frontend/src/features/chat/ChatPage.tsx` | 前端页面 | 修改：参数传递 |
| `backend/tests/test_model_parameters.py` | 测试 | 新增 |
| `frontend/__tests__/ModelTab.test.tsx` | 测试 | 新增 |

### B. 参考资料

- OpenAI API 文档: https://platform.openai.com/docs/api-reference/chat
- Anthropic API 文档: https://docs.anthropic.com/en/api/messages
- DeepSeek API 文档: https://api-docs.deepseek.com/
- Google Gemini API 文档: https://ai.google.dev/api/rest
- 项目现有架构文档: `docs/backend-architecture.md`, `docs/frontend-architecture.md`
