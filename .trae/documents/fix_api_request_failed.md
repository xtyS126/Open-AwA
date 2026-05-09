# 修复 "api request failed" 错误计划

## 问题分析

前端出现 `api request failed` 错误，通常是后端 API 返回非 2xx 响应。根据 core memory 记录，skills 接口 500 错误通常与以下问题有关：

1. **SQLite 数据库路径问题** - 已通过 `build_default_database_url()` 使用绝对路径解决
2. **skills 表数据格式兼容问题** - 已通过 `_migrate_skill_json_columns()` 迁移逻辑解决

当前问题可能是：
1. 前端错误日志输出不够详细，只显示 `[前端错误] api request failed`
2. 某些 API 接口缺少异常处理，导致错误信息不明确

## 已完成的修复

### 1. 增强前端 API 错误日志输出

修改了 `frontend/src/shared/api/api.ts` 中的错误拦截器：
- 新增 `console.error` 输出结构化错误信息
- 包含 HTTP 方法、URL、状态码、错误消息、后端详情、Request-ID
- 增强了 extra 对象，包含更多调试信息

### 2. 为后端 skills 接口添加异常处理

修改了 `backend/api/routes/skills.py`：
- `/skills` 接口：添加 try-catch 包装，日志记录具体错误
- `/skills/{skill_id}` 接口：添加 try-catch 包装，日志记录具体错误

## 验证步骤

1. 重新启动后端服务
2. 刷新前端页面
3. 检查终端输出，应该能看到更详细的错误信息，格式如：
   ```
   [API ERROR] GET /api/skills -> 500 | 获取技能列表失败: xxx | Request-ID: xxx
   ```

## 可能的根因

根据 core memory 经验，skills 接口 500 错误通常与：
1. SQLite 数据库路径配置错误
2. skills 表历史数据格式问题（YAML vs JSON）

需要查看增强后的错误日志确认具体根因。
