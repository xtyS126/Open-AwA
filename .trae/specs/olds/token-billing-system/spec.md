# Tokens计费系统规范

## 一、为什么需要这个系统

当前AI智能体架构缺乏完整的用量计费机制，无法精确追踪和统计不同模态（文字、图片、语音、视频）的API调用成本。为了实现精细化成本控制、按用量计费商业模式、以及多模型价格比较，需要构建一套完整的tokens计费系统。

## 二、功能变更

### 2.1 新增功能

- **多模态计费引擎**：支持文本、图片、语音、视频等多种内容类型的输入/输出计费
- **模型价格配置**：支持配置不同AI厂商（OpenAI、Anthropic、Google、DeepSeek、阿里通义千问、Kimi、智谱AI等）的API价格
- **用量追踪**：实时记录每次API调用的tokens消耗
- **成本统计**：支持按时间周期、用户、模型等维度统计成本
- **计费报表**：生成详细的用量和成本报表
- **预算控制**：支持设置用户或项目的预算上限
- **缓存优惠**：支持配置缓存命中折扣（如DeepSeek的1元/百万tokens缓存价格）

### 2.2 受影响的功能

- **API路由**：所有与LLM交互的API需要增加计费记录
- **执行层(executor.py)**：需要在调用LLM API时计算tokens并记录
- **前端仪表盘**：增加用量统计和成本展示模块
- **设置页面**：增加模型价格配置界面

## 三、影响范围

### 3.1 受影响的功能模块

- `core/executor.py` - LLM调用执行
- `api/routes/` - 所有AI交互API
- `frontend/pages/DashboardPage.tsx` - 仪表盘用量展示
- `frontend/pages/SettingsPage.tsx` - 价格配置界面

### 3.2 受影响的代码文件

- `backend/core/executor.py`
- `backend/api/routes/chat.py`
- `backend/db/models.py`
- `backend/billing/` - 新增计费模块
- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/stores/` - 状态管理

## 四、需求定义

### 4.1 需求：多模态计费

系统**必须提供**对不同内容类型的精确计费：

| 内容类型 | 计费方式 | 示例 |
|---------|---------|------|
| 文本输入 | 按token计费 | 用户消息、系统提示词 |
| 文本输出 | 按token计费 | AI回复内容 |
| 图片输入 | 按token计费 | 图片按固定token计算（如1024 tokens/张） |
| 图片输出 | 按token计费 | 生成的图片描述 |
| 语音输入 | 按token计费 | 语音转文字后的token |
| 语音输出 | 按token计费 | 文字转语音的token |
| 视频输入 | 按token计费 | 视频处理token |
| 视频输出 | 按token计费 | 视频生成token |

#### 场景：文本对话计费

- **WHEN** 用户发送一条文本消息
- **THEN** 系统计算输入tokens（中文按2-4字/token估算）
- **AND** 系统记录模型价格（从配置读取）
- **AND** 计算输入成本 = 输入tokens × 模型输入单价
- **AND** AI回复后计算输出tokens
- **AND** 计算输出成本 = 输出tokens × 模型输出单价
- **AND** 记录总成本到用量表

#### 场景：图片理解计费

- **WHEN** 用户上传图片并发送消息
- **THEN** 系统按固定规则计算图片token（如1024 tokens/张）
- **AND** 系统记录图片token消耗
- **AND** 结合文本tokens计算总输入成本

#### 场景：语音处理计费

- **WHEN** 用户发送语音消息
- **THEN** 系统先将语音转文字
- **AND** 按文本token计算输入成本
- **AND** 如需要语音回复，按输出token计费

### 4.2 需求：模型价格配置

系统**必须提供**灵活的模型价格配置：

#### 需求：支持多厂商价格配置

系统**必须支持**配置主流AI厂商的API价格：

```yaml
providers:
  openai:
    - model: "gpt-4.1"
      input_price: 6.00        # 美元/百万tokens
      output_price: 18.00       # 美元/百万tokens
      cache_discount: 0.75     # 缓存折扣比例
    - model: "gpt-4.1-mini"
      input_price: 0.30
      output_price: 1.20
    - model: "o1"
      input_price: 15.00
      output_price: 60.00
  
  anthropic:
    - model: "claude-3.5-sonnet"
      input_price: 3.00
      output_price: 15.00
      context_window: 200000
  
  google:
    - model: "gemini-2.0-flash"
      input_price: 0.075
      output_price: 0.30
    - model: "gemini-3.1-flash-lite"
      input_price: 0.25
      output_price: 1.50
  
  deepseek:
    - model: "deepseek-v3"
      input_price: 2.00
      output_price: 8.00
      cache_hit_price: 1.00    # 缓存命中价格
    - model: "deepseek-r1"
      input_price: 4.00
      output_price: 16.00
      cache_hit_price: 1.00
  
  alibaba:
    - model: "qwen-long"
      input_price: 0.50        # 元/百万tokens
      output_price: 2.00
    - model: "qwen3"
      input_price: 0.80
      output_price: 3.20
  
  moonshot:
    - model: "kimi-128k"
      input_price: 60.00       # 元/百万tokens
      output_price: 60.00
    - model: "kimi-vision-8k"
      input_price: 12.00
      output_price: 12.00
  
  zhipu:
    - model: "glm-4"
      input_price: 0.50
      output_price: 1.00
```

#### 场景：配置自定义价格

- **WHEN** 管理员在设置页面配置模型价格
- **THEN** 系统保存价格配置到数据库
- **AND** 系统验证价格格式（数字、币种、单位）
- **AND** 下次API调用时使用新价格计算成本

### 4.3 需求：用量追踪

#### 需求：实时记录API调用

系统**必须记录**每次LLM API调用的详细信息：

| 字段 | 说明 |
|-----|------|
| call_id | 唯一标识 |
| user_id | 用户ID |
| model | 模型名称 |
| provider | 厂商 |
| input_tokens | 输入tokens数 |
| output_tokens | 输出tokens数 |
| input_cost | 输入成本 |
| output_cost | 输出成本 |
| total_cost | 总成本 |
| currency | 币种（USD/CNY） |
| content_types | 内容类型（text/image/audio/video） |
| cache_hit | 是否缓存命中 |
| timestamp | 调用时间 |
| duration_ms | 调用耗时 |
| session_id | 会话ID |

### 4.4 需求：成本统计

#### 需求：多维度成本统计

系统**必须提供**多维度的成本统计：

- **按时间统计**：日、周、月、年
- **按用户统计**：个人用量和成本
- **按模型统计**：各模型使用量占比
- **按内容类型统计**：文本/图片/语音/视频占比
- **环比分析**：与上期对比

#### 场景：查看成本报表

- **WHEN** 用户打开成本统计页面
- **THEN** 显示本月总成本
- **AND** 显示各模型用量饼图
- **AND** 显示每日成本趋势折线图
- **AND** 显示Top 5高消耗会话
- **AND** 支持导出CSV/Excel报表

### 4.5 需求：预算控制

#### 需求：预算上限设置

系统**必须支持**设置预算上限：

| 预算类型 | 说明 |
|---------|------|
| 全局预算 | 系统总预算上限 |
| 用户预算 | 单用户预算上限 |
| 项目预算 | 单项目预算上限 |
| 模型预算 | 单模型预算上限 |

#### 场景：预算超限警告

- **WHEN** 用户用量达到预算的80%
- **THEN** 系统发送警告通知
- **WHEN** 用户用量达到预算的100%
- **THEN** 阻止新的API调用
- **AND** 提示用户升级套餐或联系管理员

## 五、技术实现

### 5.1 数据库表结构

```sql
-- 用量记录表
CREATE TABLE usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT UNIQUE NOT NULL,
    user_id TEXT,
    session_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    content_type TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    input_cost DECIMAL(10, 6) DEFAULT 0,
    output_cost DECIMAL(10, 6) DEFAULT 0,
    total_cost DECIMAL(10, 6) DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    cache_hit BOOLEAN DEFAULT FALSE,
    duration_ms INTEGER DEFAULT 0,
    metadata TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 模型价格配置表
CREATE TABLE model_pricing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_price DECIMAL(10, 4) NOT NULL,
    output_price DECIMAL(10, 4) NOT NULL,
    currency TEXT DEFAULT 'USD',
    cache_hit_price DECIMAL(10, 4),
    token_per_image INTEGER DEFAULT 1024,
    token_per_second_audio INTEGER DEFAULT 150,
    token_per_second_video INTEGER DEFAULT 2880,
    context_window INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    UNIQUE(provider, model)
);

-- 预算配置表
CREATE TABLE budget_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_type TEXT NOT NULL,
    scope_id TEXT,
    max_amount DECIMAL(12, 4) NOT NULL,
    period_type TEXT DEFAULT 'monthly',
    currency TEXT DEFAULT 'USD',
    warning_threshold REAL DEFAULT 0.8,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

-- 用户累计用量表
CREATE TABLE user_usage_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cost DECIMAL(12, 4) DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    UNIQUE(user_id, period_start)
);
```

### 5.2 后端模块结构

```
backend/
├── billing/                          # 计费模块
│   ├── __init__.py
│   ├── engine.py                    # 计费引擎
│   ├── calculator.py               # 成本计算器
│   ├── tracker.py                  # 用量追踪器
│   ├── models.py                   # 计费数据模型
│   ├── pricing_manager.py           # 价格配置管理
│   ├── budget_manager.py           # 预算管理
│   ├── reporter.py                 # 报表生成
│   └── routers/
│       └── billing.py              # 计费API路由
```

### 5.3 计费流程

```
用户消息
    ↓
[1] 理解层(comprehension.py) - 计算输入tokens
    ↓
[2] 规划层(planner.py) - 选择模型
    ↓
[3] 执行层(executor.py)
    ├─ 调用计费引擎(billing/engine.py)
    │   ├─ 检查预算
    │   ├─ 记录开始
    │   └─ 检查缓存
    ├─ 调用LLM API
    └─ 计算输出tokens
    ↓
[4] 计费引擎 - 计算成本
    ├─ 输入成本 = input_tokens × input_price
    ├─ 输出成本 = output_tokens × output_price
    ├─ 总成本 = 输入成本 + 输出成本
    └─ 缓存折扣（如适用）
    ↓
[5] 记录到usage_records表
    ↓
[6] 更新user_usage_summary
    ↓
[7] 反馈层(feedback.py) - 返回结果
```

### 5.4 Tokens计算规则

#### 文本Tokens估算

| 语言 | 估算规则 |
|-----|---------|
| 英文 | 约1 token ≈ 4个字符 |
| 中文 | 约1 token ≈ 1-2个汉字 |
| 混合 | 按实际模型编码计算 |

#### 多模态Tokens转换

| 内容类型 | 转换规则 |
|---------|---------|
| 图片 | 固定1024 tokens/张（Kimi标准） |
| 语音 | 约150 tokens/秒 |
| 视频 | 约2880 tokens/秒 |

## 六、API接口设计

### 6.1 计费相关API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/billing/usage | 获取用量记录 |
| GET | /api/billing/cost | 获取成本统计 |
| GET | /api/billing/models | 获取模型价格列表 |
| PUT | /api/billing/models/{id} | 更新模型价格 |
| GET | /api/billing/budget | 获取预算配置 |
| PUT | /api/billing/budget | 设置预算 |
| GET | /api/billing/report | 生成报表 |

### 6.2 请求/响应示例

#### 获取成本统计

```
GET /api/billing/cost?period=monthly&user_id=user123

Response:
{
  "period": "monthly",
  "total_cost": 125.50,
  "currency": "USD",
  "total_input_tokens": 1500000,
  "total_output_tokens": 800000,
  "by_model": [
    {
      "model": "gpt-4.1",
      "input_tokens": 1000000,
      "output_tokens": 500000,
      "cost": 75.00
    },
    {
      "model": "claude-3.5-sonnet",
      "input_tokens": 500000,
      "output_tokens": 300000,
      "cost": 50.50
    }
  ],
  "by_content_type": {
    "text": 80.00,
    "image": 30.50,
    "audio": 15.00
  },
  "trend": [
    {"date": "2026-03-01", "cost": 10.50},
    {"date": "2026-03-02", "cost": 8.20}
  ]
}
```

#### 更新模型价格

```
PUT /api/billing/models/claude-3.5-sonnet

Request:
{
  "input_price": 3.50,
  "output_price": 17.50
}

Response:
{
  "success": true,
  "model": "claude-3.5-sonnet",
  "new_prices": {
    "input_price": 3.50,
    "output_price": 17.50
  }
}
```

## 七、前端实现

### 7.1 仪表盘增强

在DashboardPage.tsx中添加：
- 本月成本卡片
- 用量趋势图
- 模型使用分布饼图
- 预算进度条

### 7.2 设置页面增强

在SettingsPage.tsx中添加：
- 模型价格配置表格
- 预算设置表单
- 币种选择（USD/CNY）
- 价格导入/导出功能

### 7.3 新增计费页面

创建 `BillingPage.tsx`：
- 用量明细列表
- 成本分析图表
- 报表导出功能
- 预算管理

## 八、修改需求

### 8.1 修改：core/executor.py

**变更原因**：需要集成计费逻辑
**迁移方案**：
1. 在LLM调用前后添加计费钩子
2. 记录输入输出tokens
3. 调用计费引擎计算成本

### 8.2 修改：api/schemas.py

**变更原因**：添加计费相关数据模型
**迁移方案**：
1. 添加UsageRecord模型
2. 添加ModelPricing模型
3. 添加CostStatistics模型

## 九、非功能性需求

### 9.1 性能需求

- 计费记录写入延迟 < 10ms
- 成本统计查询响应 < 500ms
- 支持每日百万级调用记录

### 9.2 数据需求

- 用量记录保留至少12个月
- 支持数据导出备份
- 数据准确性误差 < 0.1%

### 9.3 安全需求

- 计费数据只读权限控制
- 价格配置需要管理员权限
- 操作日志完整记录

---

**规范版本**：1.0.0
**创建日期**：2026年3月22日
**参考文档**：ai-models-api-pricing-2026.md
