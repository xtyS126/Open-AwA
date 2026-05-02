# 部署与运行说明

本文档描述当前仓库在本地开发环境中的启动方式、关键环境变量和部署时需要关注的事项。内容以当前代码实现为准。

## 1. 运行形态

当前仓库主要由两部分组成：

- 后端 FastAPI 服务：`d:\代码\Open-AwA\backend`
- 前端 Vite 开发服务：`d:\代码\Open-AwA\frontend`

后端入口：

- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L1-L95)

前端入口：

- [main.tsx](file:///d:/代码/Open-AwA/frontend/src/main.tsx)
- [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L1-L91)

## 2. 本地开发部署

### 2.1 启动后端

```powershell
cd d:\代码\Open-AwA\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

或者使用 uvicorn：

```powershell
cd d:\代码\Open-AwA\backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

后端会提供：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/health`

### 2.2 启动前端

```powershell
cd d:\代码\Open-AwA\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

前端默认地址：

- `http://127.0.0.1:5173`

## 3. 启动时的后端初始化行为

根据当前实现，后端启动时会完成以下工作：

1. 初始化数据库表
2. 创建计费模块数据库表
3. 初始化默认模型定价
4. 清理旧版默认模型配置
5. 同步内置工具技能配置
6. 挂载各业务路由

参考代码：

- [lifespan](file:///d:/代码/Open-AwA/backend/main.py#L26-L49)
- [init_db](file:///d:/代码/Open-AwA/backend/db/models.py#L225-L227)

## 4. 关键环境变量

当前可直接从代码确认的配置主要来自：

- [settings.py](file:///d:/代码/Open-AwA/backend/config/settings.py#L24-L59)
- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L22-L23)

### 4.1 后端配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./openawa.db` | 主数据库连接字符串 |
| `SECRET_KEY` | 未配置时运行期随机生成 | JWT 与安全相关配置，生产环境必须显式设置 |
| `API_V1_STR` | `/api` | API 前缀 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token 有效期 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `SANDBOX_TIMEOUT` | `30` | 插件沙箱超时秒数 |
| `SANDBOX_MEMORY_LIMIT` | `512m` | 插件沙箱内存配置值 |
| `VECTOR_DB_PATH` | `backend/data/vector_db` | 长期记忆 ChromaDB 持久化目录 |
| `MEMORY_EMBEDDING_PROVIDER` | 自动选择 | 长期记忆嵌入提供方，可选 `hash`、`openai`、`sentence-transformers` |
| `OPENAI_API_KEY` | `None` | 模型供应商配置 |
| `ANTHROPIC_API_KEY` | `None` | 模型供应商配置 |
| `DEEPSEEK_API_KEY` | `None` | 模型供应商配置 |
| `ALLOWED_ORIGINS` | 默认允许 `localhost:5173`、`localhost:8000` | CORS 来源，来自环境变量 |

### 4.2 生产环境至少应显式设置

- `SECRET_KEY`
- `DATABASE_URL`
- `ALLOWED_ORIGINS`
- 实际使用的模型 API Key

如果启用了向量记忆检索，建议同时确认：

- `VECTOR_DB_PATH` 指向可写目录
- `MEMORY_EMBEDDING_PROVIDER` 与实际部署能力匹配
- 若使用 `openai` 嵌入，`OPENAI_API_KEY` 已配置

## 5. 数据库相关说明

当前代码默认使用 SQLite：

- `openawa.db`
- E2E 测试中使用 `openawa_e2e.db`

长期记忆向量数据默认使用 ChromaDB 持久化到：

- `backend/data/vector_db`

数据库模型集中在：

- [models.py](file:///d:/代码/Open-AwA/backend/db/models.py#L20-L235)

主要表包括：

- 用户表 `users`
- 技能表 `skills`
- 插件表 `plugins`
- 记忆表 `short_term_memory`、`long_term_memory`
- 工作流表 `workflows`、`workflow_steps`、`workflow_executions`
- 经验表 `experience_memory`
- 行为日志表 `behavior_logs`
- 提示词表 `prompt_configs`
- 会话记录表 `conversation_records`
- 若干计费相关表

## 5.1 向量记忆部署注意事项

长期记忆增强能力依赖 ChromaDB 持久化目录和嵌入提供方配置。部署时建议确认：

- 应用进程对 `VECTOR_DB_PATH` 拥有读写权限
- 如使用容器部署，应为向量目录单独挂载持久卷
- 如使用 `sentence-transformers`，镜像或运行环境中需要预装对应依赖
- 如使用 `openai` 嵌入，需评估外部 API 延迟和成本

## 5.2 工作流与工具部署注意事项

工作流能力会调用文件管理、终端执行、网页搜索等内置工具。部署时建议：

- 明确文件工具的允许目录范围，避免暴露整个宿主机文件系统
- 终端执行能力仅在受控环境中启用，并结合沙箱或容器隔离
- 对工作流执行记录和工具调用日志进行保留，便于审计与回溯

## 6. CORS 与前后端联调

后端在启动时读取 `ALLOWED_ORIGINS`，若未配置则默认允许：

- `http://localhost:5173`
- `http://localhost:8000`

参考：

- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L22-L24)
- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L59-L65)

前端默认通过相对路径 `/api` 调用后端：

- [api.ts](file:///d:/代码/Open-AwA/frontend/src/services/api.ts#L1-L20)

因此在本地开发中，通常需要通过 Vite 代理或同源部署方式保证 `/api` 请求能正确到达后端。如果当前前端运行环境没有设置代理，需要自行确认浏览器访问路径是否与后端对齐。

## 7. 鉴权与登录说明

后端提供：

- 注册：`POST /api/auth/register`
- 登录：`POST /api/auth/login`
- 当前用户：`GET /api/auth/me`

参考：

- [auth.py](file:///d:/代码/Open-AwA/backend/api/routes/auth.py#L14-L62)

前端当前存在一个开发期初始化逻辑：如果本地没有 token，会尝试自动注册并登录一个临时测试用户。

参考：

- [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L20-L53)

这适合本地联调，但不应直接视为正式生产登录流程。

## 8. 插件相关部署注意事项

插件上传接口会直接解压 zip 到插件目录，并执行插件发现逻辑：

- [upload_plugin](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L371-L421)

因此在部署环境中建议：

- 控制插件上传权限
- 对插件目录做备份
- 配合热更新与回滚能力进行变更管理
- 避免无审查地导入第三方插件包

## 9. 计费与模型配置部署注意事项

后端启动时会初始化默认模型定价配置，计费相关接口集中在：

- [billing.py](file:///d:/代码/Open-AwA/backend/billing/routers/billing.py#L14-L260)

前端聊天页与计费页会使用模型配置和成本统计接口：

- [ChatPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/ChatPage.tsx#L26-L79)
- [BillingPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/BillingPage.tsx#L42-L74)
- [modelsApi.ts](file:///d:/代码/Open-AwA/frontend/src/services/modelsApi.ts#L60-L115)

建议部署前检查：

- 是否已经配置需要的模型 API Key
- 默认模型是否可用
- 预算与成本统计接口是否符合当前业务需求

## 10. 部署后最小验证清单

建议部署后依次检查：

1. `GET /health` 返回 `{"status":"healthy"}`
2. 能否注册和登录用户
3. 前端首页是否正常加载
4. 聊天页是否能拉取模型配置
5. 插件页、技能页、记忆页是否能正常请求列表接口
6. 计费页是否能读取成本统计
7. 会话记录与行为统计接口是否可访问

## 11. 当前文档边界

本文档主要描述当前代码可观察到的本地部署方式。对于容器化、反向代理、TLS、分布式部署、对象存储、消息队列等能力，当前仓库中未看到完整落地方案，因此本文档不做虚构性扩展。
