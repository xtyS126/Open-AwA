# Tokens计费系统实施检查清单

## 一、数据库与数据模型检查

### 1.1 数据库表结构

- [x] `usage_records` 用量记录表创建成功
- [x] `model_pricing` 模型价格配置表创建成功
- [x] `budget_configs` 预算配置表创建成功
- [x] `user_usage_summary` 用户累计用量表创建成功
- [x] 数据库迁移脚本正常执行

### 1.2 数据模型

- [x] `billing/models.py` 中 UsageRecord 模型定义正确
- [x] `billing/models.py` 中 ModelPricing 模型定义正确
- [x] `billing/models.py` 中 BudgetConfig 模型定义正确
- [x] `billing/models.py` 中 UserUsageSummary 模型定义正确

## 二、后端计费核心模块检查

### 2.1 成本计算器 (`billing/calculator.py`)

- [x] 文本tokens估算函数正常工作
- [x] 中文tokens估算正确（约1-2字/token）
- [x] 英文tokens估算正确（约4字符/token）
- [x] 图片tokens转换正确（1024 tokens/张）
- [x] 语音tokens转换正确（150 tokens/秒）
- [x] 视频tokens转换正确（2880 tokens/秒）
- [x] 成本计算公式正确
- [x] 缓存折扣计算正确

### 2.2 价格配置管理 (`billing/pricing_manager.py`)

- [x] 模型价格CRUD操作正常
- [x] 按厂商查询价格功能正常
- [x] 按模型查询价格功能正常
- [x] 价格配置验证功能正常
- [x] 默认价格数据初始化成功（8个厂商）

### 2.3 用量追踪器 (`billing/tracker.py`)

- [x] 用量记录创建成功
- [x] 用量记录查询成功
- [x] 会话级别用量聚合正确
- [x] 用户级别用量统计正确

### 2.4 预算管理 (`billing/budget_manager.py`)

- [x] 预算配置CRUD功能正常
- [x] 预算检查逻辑正确
- [x] 80%警告阈值检测正常
- [x] 100%超限拦截正常

### 2.5 计费引擎 (`billing/engine.py`)

- [x] LLM调用钩子集成成功
- [x] 自动计费记录功能正常
- [x] 成本统计聚合正确
- [x] 集成到 main.py 成功

### 2.6 报表生成器 (`billing/reporter.py`)

- [x] 按时间维度统计正确
- [x] 按用户维度统计正确
- [x] 按模型维度统计正确
- [x] 按内容类型统计正确
- [x] CSV导出功能正常

### 2.7 计费API路由 (`billing/routers/billing.py`)

- [x] GET /api/billing/usage 返回正确
- [x] GET /api/billing/cost 返回正确
- [x] GET /api/billing/models 返回正确
- [x] PUT /api/billing/models/{id} 更新成功
- [x] GET /api/billing/budget 返回正确
- [x] PUT /api/billing/budget 设置成功
- [x] GET /api/billing/report 生成成功
- [x] GET /api/billing/session/{id} 返回正确
- [x] GET /api/billing/estimate 返回正确
- [x] POST /api/billing/initialize-pricing 初始化成功

## 三、修改现有模块检查

### 3.1 main.py 修改

- [x] 集成计费API路由成功
- [x] 计费表自动创建成功
- [x] 默认价格初始化成功

## 四、前端实现检查

### 4.1 计费页面 (`BillingPage.tsx`)

- [x] 计费页面路由配置正确
- [x] 用量明细列表显示正常
- [x] 成本分析图表显示正常
- [x] 时间筛选功能正常
- [x] 用户筛选功能正常
- [x] 模型筛选功能正常
- [x] 导出功能正常

### 4.2 仪表盘修改 (`DashboardPage.tsx`)

- [x] 本月成本卡片显示正确
- [x] 用量趋势折线图显示正确
- [x] 模型使用分布显示正确
- [x] /api/billing/cost 接口调用成功

### 4.3 设置页面修改 (`SettingsPage.tsx`)

- [x] 模型价格配置区域显示正确
- [x] 价格表格展示正确
- [x] 价格编辑功能正常
- [x] 币种显示正确（USD/CNY）
- [x] 按厂商分组显示正常

### 4.4 计费API服务 (`services/billingApi.ts`)

- [x] 获取用量记录API正常
- [x] 获取成本统计API正常
- [x] 获取模型价格API正常
- [x] 更新模型价格API正常
- [x] 获取预算API正常
- [x] 设置预算API正常
- [x] 报表导出API正常

### 4.5 App和Sidebar更新

- [x] 路由配置正确
- [x] 菜单项添加成功

## 五、初始化数据检查

### 5.1 默认价格数据

- [x] OpenAI模型价格添加成功
  - [x] GPT-4.1 (6/18 USD)
  - [x] GPT-4.1-mini
  - [x] GPT-4.1-nano
  - [x] o1 (15/60 USD)
  - [x] GPT-4o
  - [x] GPT-4o-mini

- [x] Anthropic模型价格添加成功
  - [x] Claude 3.5 Sonnet (3/15 USD)
  - [x] Claude 3.5 Haiku

- [x] Google模型价格添加成功
  - [x] Gemini 2.0 Flash (0.075/0.30 USD)
  - [x] Gemini 3.1 Flash-Lite (0.25/1.50 USD)
  - [x] Gemini 2.0 Pro

- [x] DeepSeek模型价格添加成功
  - [x] DeepSeek-V3 (2/8 CNY，含缓存价格1元)
  - [x] DeepSeek-R1 (4/16 CNY，含缓存价格1元)
  - [x] DeepSeek-Chat

- [x] 阿里通义千问价格添加成功
  - [x] Qwen-Long (0.5 CNY)
  - [x] Qwen3
  - [x] Qwen2.5-Turbo

- [x] Kimi模型价格添加成功
  - [x] Kimi 128K (60 CNY)
  - [x] Kimi Vision 8K (12 CNY)
  - [x] Kimi Vision 32K (24 CNY)
  - [x] Kimi Vision 128K (60 CNY)

- [x] 智谱AI价格添加成功
  - [x] GLM-4
  - [x] GLM-4-Plus

## 六、实现总结

### 通过项目
全部核心功能已实现，包括：
- 4张数据库表
- 6个后端核心模块
- 10个API端点
- 完整的前端计费页面
- 仪表盘增强
- 设置页面计费配置
- 8个AI厂商的默认价格

### 备注
- 系统启动时自动初始化默认价格数据
- 支持多币种（USD/CNY）
- 支持多模态计费（文本/图片/语音/视频）
- 支持预算控制和警告
