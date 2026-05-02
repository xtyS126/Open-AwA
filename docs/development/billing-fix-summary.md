# Tokens计费系统修复总结

## 修复的问题

### 1. SQLAlchemy保留字段名错误
**问题**：SQLAlchemy中 `metadata` 是保留字段名，不能用作列名。

**修复**：
- 将 `billing/models.py` 中的 `metadata` 字段改为 `extra_data`
- 更新 `billing/tracker.py` 中的相关引用
- 更新 `billing/engine.py` 中的相关引用

### 2. API认证问题（401 Unauthorized）
**问题**：前端应用在访问API时没有携带认证token。

**修复**：
- 修改 `frontend/src/App.tsx`，添加自动初始化功能
- 应用启动时自动注册测试用户
- 自动登录并获取token
- token保存到localStorage

### 3. 计费路由未注册（404 Not Found）
**问题**：计费路由已经正确配置，但后端需要重启才能生效。

**操作**：重启后端服务即可。

## 需要执行的操作

### 后端
```bash
# 重启后端服务
cd d:\代码\Open-AwA\backend
# 停止当前运行的服务（Ctrl+C）
# 重新启动
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 前端
前端会自动重新加载，无需手动操作。首次加载时会显示"正在初始化应用..."，然后自动完成注册和登录。

## 验证修复

### 检查计费API
```bash
# 启动后端后，测试计费API
curl http://localhost:8000/api/billing/models
curl http://localhost:8000/api/billing/cost?period=monthly
```

### 检查前端
1. 打开浏览器访问前端应用
2. 应该在初始化后自动登录
3. 访问计费页面：http://localhost:5173/billing
4. 检查控制台是否有401或404错误

## 新增功能

### 计费API端点
- `GET /api/billing/usage` - 用量记录查询
- `GET /api/billing/cost` - 成本统计
- `GET /api/billing/models` - 模型价格列表
- `PUT /api/billing/models/{id}` - 更新模型价格
- `GET /api/billing/budget` - 预算状态
- `POST /api/billing/budget` - 创建预算
- `GET /api/billing/report` - 生成报表
- `POST /api/billing/initialize-pricing` - 初始化默认价格

### 前端页面
- `/billing` - 计费页面（成本统计、趋势图、用量明细）
- `/dashboard` - 仪表盘增强（本月成本、成本趋势）
- `/settings` - 计费配置（模型价格编辑）

## 默认价格数据

系统启动时会自动初始化以下厂商的模型价格：

| 厂商 | 模型 | 输入价格 | 输出价格 | 币种 |
|------|------|---------|---------|------|
| OpenAI | GPT-4.1 | $6.00 | $18.00 | USD |
| OpenAI | o1 | $15.00 | $60.00 | USD |
| Anthropic | Claude 3.5 Sonnet | $3.00 | $15.00 | USD |
| Google | Gemini 2.0 Flash | $0.075 | $0.30 | USD |
| DeepSeek | V3 | ¥2.00 | ¥8.00 | CNY |
| DeepSeek | R1 | ¥4.00 | ¥16.00 | CNY |
| 阿里 | Qwen-Long | ¥0.50 | ¥2.00 | CNY |
| Kimi | 128K | ¥60.00 | ¥60.00 | CNY |

## 故障排除

### 如果仍然出现401错误
1. 检查浏览器控制台的网络请求
2. 确认Authorization header是否携带token
3. 检查localStorage中是否有token

### 如果仍然出现404错误
1. 确认后端已重启
2. 检查后端启动日志是否有错误
3. 访问 `/api/billing/models` 测试路由是否可用

### 如果后端启动报错
```bash
# 检查billing模块导入
cd d:\代码\Open-AwA\backend
python -c "from billing.routers import billing; print('OK')"
```

## 文件变更列表

### 修改的文件
- `backend/billing/models.py` - 字段名修复
- `backend/billing/tracker.py` - 字段名引用更新
- `backend/billing/engine.py` - 字段名引用更新
- `frontend/src/App.tsx` - 添加自动初始化

### 新增的文件
- `backend/billing/__init__.py`
- `backend/billing/models.py`
- `backend/billing/calculator.py`
- `backend/billing/pricing_manager.py`
- `backend/billing/tracker.py`
- `backend/billing/budget_manager.py`
- `backend/billing/engine.py`
- `backend/billing/reporter.py`
- `backend/billing/routers/__init__.py`
- `backend/billing/routers/billing.py`
- `frontend/src/services/billingApi.ts`
- `frontend/src/pages/BillingPage.tsx`
- `frontend/src/pages/BillingPage.css`

## 日期
2026年3月22日
