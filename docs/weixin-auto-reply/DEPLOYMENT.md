# 微信自动回复模块部署指引

本文档适用于 `v2.0.0` 版本的微信自动回复模块的部署与运行维护。

## 1. 部署前置条件

1. **Python 环境**：要求 Python 3.9+。
2. **依赖包**：
   确保安装了 `httpx`, `loguru`, `sqlalchemy` 等核心依赖包。可以通过后端的 `requirements.txt` 或 `pip install` 进行安装。
3. **网络要求**：
   所在服务器必须能稳定访问微信官方接口：`https://ilinkai.weixin.qq.com`。由于本项目默认在中国境内网络环境运行，请确保无严格的防火墙拦截该域名。

## 2. 目录结构与状态文件说明

微信自动回复会在项目的 `.openawa/weixin/accounts` 目录下生成状态与游标文件，请确保应用对该目录拥有**读写权限**：
- `{account_id}.sync.json`：存放拉取消息的轮询游标 (Cursor)。
- `{account_id}.context-tokens.json`：存放各用户的上下文 Token，用于发消息。
- `{account_id}.auto-reply.json`：存放自动回复的运行状态与最近 500 条消息的幂等处理记录。

## 3. 部署步骤

1. **数据库迁移**
   微信自动回复模块依赖 `WeixinBinding` 和 `WeixinAutoReplyRule` 表，请确保数据库 Schema 已更新到最新版本。
   ```bash
   cd backend
   alembic upgrade head # 或使用 python migrate_db.py 视具体配置而定
   ```

2. **环境变量配置**
   检查后端环境变量配置文件 `.env`（或对应的环境配置）：
   ```env
   # 如有特定代理，请在此配置，否则保持默认
   # HTTP_PROXY=...
   ```

3. **启动后端服务**
   启动 FastAPI/后台任务服务：
   ```bash
   cd backend
   python main.py
   ```
   *服务启动后，当用户在前端开启“微信自动回复”时，系统将动态拉起该用户的后台轮询任务。*

## 4. 运行验证与健康检查

通过访问对应用户的状态诊断接口（`get_status`）检查服务是否运行正常。
返回的数据应包含：
- `binding_ready`: true
- `auto_reply_enabled`: true
- `auto_reply_running`: true
- `last_poll_status`: ok

如发现 `last_poll_status` 出现 `error` 或 `timeout`，请排查网络连通性及微信 Token 是否已过期。

## 5. 常见问题排查

1. **日志监控**：
   所有微信自动回复日志通过 `loguru` 打印，具有统一的 `module="weixin.auto_reply"` 绑定标签。可以通过此标签在日志管理系统中快速过滤相关问题。
2. **Token 失效 (401)**：
   若服务日志中频繁报出 `WEIXIN_TOKEN_EXPIRED`，说明微信登录已过期，需引导用户重新扫码登录并刷新。
3. **并发写入权限错误 (Windows)**：
   系统内部已引入 `threading.RLock` 与指数退避重试来解决 Windows 下的并发文件锁问题，但仍需确保当前启动进程拥有该目录的最高权限。
