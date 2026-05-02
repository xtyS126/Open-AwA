# 外键引用错误修复

## 问题描述

启动后端时出现以下错误：

```
sqlalchemy.exc.NoReferencedTableError: Foreign key associated with column 'usage_records.user_id' could not find table 'users' with which to generate a foreign key to target column 'id'
```

## 问题原因

`usage_records` 表定义了一个外键引用 `users` 表，但：
1. `users` 表在另一个数据库模块中定义
2. 使用了不同的 Base 类，导致表创建顺序问题

## 修复方案

### 1. 移除外键约束
修改 `backend/billing/models.py`：

**之前**：
```python
user_id = Column(String, ForeignKey("users.id"), index=True)
```

**之后**：
```python
user_id = Column(String, index=True)
```

### 2. 优化日志输出
在 `backend/main.py` 中添加更详细的日志，便于调试：

```python
init_db()
logger.info("Database initialized")
BillingBase.metadata.create_all(bind=engine)
logger.info("Billing tables created")
```

## 修改的文件

1. `backend/billing/models.py` - 移除 ForeignKey 约束
2. `backend/main.py` - 优化日志输出

## 验证修复

### 测试模型导入
```bash
cd d:\代码\Open-AwA\backend
python -c "from billing.models import UsageRecord, ModelPricing; print('Models imported successfully')"
```

### 测试应用加载
```bash
cd d:\代码\Open-AwA\backend
python -c "from main import app; print('App loaded successfully')"
```

## 重新启动后端

现在可以重新启动后端服务了：

```bash
cd d:\代码\Open-AwA\backend
python main.py
```

应该能看到以下日志：
```
INFO:     Started server process [xxxx]
INFO:     Waiting for application startup.
2026-03-22 xx:xx:xx | INFO | Starting up Open-AwA AI Agent
2026-03-22 xx:xx:xx | INFO | Database initialized
2026-03-22 xx:xx:xx | INFO | Billing tables created
2026-03-22 xx:xx:xx | INFO | Initialized xx model pricing entries
INFO:     Application startup complete.
```

## 影响说明

移除外键约束不会影响功能，因为：
1. `user_id` 仍然是索引字段，可以快速查询
2. 应用层可以通过 JOIN 查询来获取用户信息
3. 这样避免了表创建顺序的依赖问题

## 下一步

1. 重启后端服务
2. 测试前端应用
3. 验证计费API是否正常工作

## 日期
2026年3月22日
