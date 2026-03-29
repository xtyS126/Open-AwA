# Tokens计费系统实施任务清单

## Phase 1: 数据库与数据模型

- [x] 1.1: 创建数据库表结构
  - [x] 创建 `usage_records` 用量记录表
  - [x] 创建 `model_pricing` 模型价格配置表
  - [x] 创建 `budget_configs` 预算配置表
  - [x] 创建 `user_usage_summary` 用户累计用量表
  - [x] 编写数据库迁移脚本

- [x] 1.2: 创建计费数据模型
  - [x] 在 `billing/models.py` 中定义 UsageRecord 模型
  - [x] 在 `billing/models.py` 中定义 ModelPricing 模型
  - [x] 在 `billing/models.py` 中定义 BudgetConfig 模型
  - [x] 在 `billing/models.py` 中定义 UserUsageSummary 模型

## Phase 2: 后端计费核心模块

- [x] 2.1: 实现成本计算器 (`billing/calculator.py`)
  - [x] 实现文本tokens估算函数（中英文）
  - [x] 实现多模态tokens转换函数（图片/语音/视频）
  - [x] 实现成本计算逻辑
  - [x] 实现缓存折扣计算

- [x] 2.2: 实现价格配置管理 (`billing/pricing_manager.py`)
  - [x] 实现模型价格CRUD操作
  - [x] 实现按厂商/模型查询价格
  - [x] 实现价格配置验证
  - [x] 初始化默认价格数据（基于ai-models-api-pricing-2026.md）

- [x] 2.3: 实现用量追踪器 (`billing/tracker.py`)
  - [x] 实现用量记录创建
  - [x] 实现用量记录查询
  - [x] 实现会话级别的用量聚合
  - [x] 实现用户级别的用量统计

- [x] 2.4: 实现预算管理 (`billing/budget_manager.py`)
  - [x] 实现预算配置CRUD
  - [x] 实现预算检查逻辑
  - [x] 实现预算警告阈值检测
  - [x] 实现预算超限拦截

- [x] 2.5: 实现计费引擎 (`billing/engine.py`)
  - [x] 实现LLM调用钩子集成
  - [x] 实现自动计费记录
  - [x] 实现成本统计聚合
  - [x] 集成到 executor.py

- [x] 2.6: 实现报表生成器 (`billing/reporter.py`)
  - [x] 实现按时间维度的成本统计
  - [x] 实现按用户维度的成本统计
  - [x] 实现按模型维度的成本统计
  - [x] 实现按内容类型的成本统计
  - [x] 实现CSV导出功能

- [x] 2.7: 实现计费API路由 (`billing/routers/billing.py`)
  - [x] 实现 GET /api/billing/usage 接口
  - [x] 实现 GET /api/billing/cost 接口
  - [x] 实现 GET /api/billing/models 接口
  - [x] 实现 PUT /api/billing/models/{id} 接口
  - [x] 实现 GET /api/billing/budget 接口
  - [x] 实现 PUT /api/billing/budget 接口
  - [x] 实现 GET /api/billing/report 接口

## Phase 3: 修改现有模块

- [x] 3.1: 修改 main.py 集成计费路由
  - [x] 集成计费API路由
  - [x] 添加计费表自动创建
  - [x] 添加默认价格初始化

- [x] 3.2: 添加计费相关API端点
  - [x] 用量记录查询
  - [x] 成本统计查询
  - [x] 模型价格管理

## Phase 4: 前端实现

- [x] 4.1: 创建计费页面 (`BillingPage.tsx`)
  - [x] 创建计费页面路由
  - [x] 实现用量明细列表组件
  - [x] 实现成本分析图表（Recharts）
  - [x] 实现筛选功能（时间/用户/模型）
  - [x] 实现导出功能

- [x] 4.2: 修改仪表盘 (`DashboardPage.tsx`)
  - [x] 添加本月成本卡片
  - [x] 添加用量趋势折线图
  - [x] 添加模型使用分布
  - [x] 调用 /api/billing/cost 获取数据

- [x] 4.3: 修改设置页面 (`SettingsPage.tsx`)
  - [x] 添加模型价格配置区域
  - [x] 实现价格表格展示
  - [x] 实现价格编辑功能
  - [x] 实现币种显示（USD/CNY）
  - [x] 添加按厂商分组显示

- [x] 4.4: 创建计费API服务 (`services/billingApi.ts`)
  - [x] 实现获取用量记录API
  - [x] 实现获取成本统计API
  - [x] 实现获取/更新模型价格API
  - [x] 实现获取/设置预算API
  - [x] 实现报表导出API

- [x] 4.5: 更新App和Sidebar
  - [x] 添加计费页面路由
  - [x] 添加计费菜单项

## Phase 5: 初始化数据

- [x] 5.1: 初始化默认价格数据
  - [x] 添加OpenAI模型价格（GPT-4.1, o1等）
  - [x] 添加Anthropic模型价格（Claude 3.5 Sonnet）
  - [x] 添加Google模型价格（Gemini 2.0 Flash, 3.1 Flash-Lite）
  - [x] 添加DeepSeek模型价格（V3, R1，含缓存价格）
  - [x] 添加阿里通义千问价格（Qwen-Long, Qwen3）
  - [x] 添加Kimi模型价格（128K, Vision）
  - [x] 添加智谱AI价格（GLM-4）

## Phase 6: 测试与验证

- [x] 6.1: 代码完整性验证
  - [x] 所有模块文件创建完成
  - [x] API路由正确配置
  - [x] 前端组件完整

## 实现总结

Tokens计费系统已完成全部核心功能开发，包括：

**后端模块：**
- `billing/models.py` - 数据模型（4张表）
- `billing/calculator.py` - 多模态成本计算
- `billing/pricing_manager.py` - 价格配置管理
- `billing/tracker.py` - 用量追踪
- `billing/budget_manager.py` - 预算管理
- `billing/engine.py` - 计费引擎
- `billing/reporter.py` - 报表生成
- `billing/routers/billing.py` - API路由（10个端点）

**前端模块：**
- `services/billingApi.ts` - API服务
- `pages/BillingPage.tsx` - 计费页面
- `pages/BashboardPage.tsx` - 仪表盘增强
- `pages/SettingsPage.tsx` - 计费配置
- `App.tsx` - 路由更新
- `components/Sidebar.tsx` - 菜单更新

**支持厂商：**
- OpenAI (GPT-4.1, o1, GPT-4o)
- Anthropic (Claude 3.5 Sonnet)
- Google (Gemini 2.0 Flash, 3.1 Flash-Lite)
- DeepSeek (V3, R1，含缓存价格)
- 阿里通义千问 (Qwen-Long, Qwen3)
- Kimi (128K, Vision系列)
- 智谱AI (GLM-4)
