# Open-AwA 上线迁移指南

本文档旨在为运维与开发人员提供 Open-AwA 项目从测试/预发布环境平滑迁移并部署到生产环境的详细操作指南。

## 1. 迁移前准备

- **环境要求确认**：
  - **后端**：Python 3.12+ (推荐 3.12.7)，推荐在虚拟环境（`venv`或`conda`）中运行。
  - **前端**：Node.js 18+ (推荐 20+)，npm。
  - **数据库**：SQLite3（本项目使用本地 SQLite 数据库 `openawa.db`，若涉及外部数据库需预留访问权限）。
- **数据备份**：
  - 务必在执行任何数据库迁移前备份原有的 SQLite 数据库文件（默认位置：`d:\代码\Open-AwA\openawa.db` 或项目根目录下的 `openawa.db`）。

## 2. 后端迁移与部署步骤

### 2.1 获取最新代码并安装依赖

进入后端目录，拉取最新代码并更新依赖：

```bash
cd backend
git pull origin main
pip install -r requirements.txt
```

### 2.2 数据库迁移与初始化

本次更新包含了技能（skills）与经验记忆（experience_memory）相关表结构的变动。请依次执行以下脚本：

```bash
# 1. 执行表结构迁移脚本，自动添加缺失字段（如category, tags, dependencies等）
python migrate_db.py

# 2. 运行经验记忆初始化脚本，加载默认数据
python init_experience_memory.py
```

执行完毕后，控制台应输出“完整数据库迁移完成”以及初始化成功的提示。

### 2.3 环境变量与配置更新

生产环境对安全性和计费有更严格的要求。请在部署服务器的环境变量配置（或 `.env` 文件）中添加/更新以下配置：

- `ENVIRONMENT=production`：必须设置。
- `SECRET_KEY=<你的随机安全字符串>`：必须设置（近期修复中已加入强制校验，若在 `production` 环境下缺少该配置，服务将无法启动）。可以使用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成。

### 2.4 启动后端服务

使用 `uvicorn`（或通过 `gunicorn` 结合 `uvicorn.workers.UvicornWorker`）启动服务：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

## 3. 前端迁移与部署步骤

### 3.1 安装依赖与构建

进入前端目录，安装最新的 npm 依赖并执行生产构建：

```bash
cd ../frontend
npm install
npm run build
```

构建完成后，所有的静态资源将生成在 `frontend/dist` 目录中。

### 3.2 部署静态资源

将 `frontend/dist` 目录下的所有文件部署到 Nginx 或其他静态资源服务器。
示例 Nginx 配置：

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    root /path/to/Open-AwA/frontend/dist;
    index index.html;

    # 支持 React Router 的 History 路由模式
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 请求代理至后端
    location /api/ {
        proxy_pass http://127.0.0.0:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 4. 迁移后验证

迁移完成后，请进行以下线上冒烟测试验证：

1. **后端健康检查**：访问 `http://<domain>/api/health` 确认服务运行正常。
2. **安全配置验证**：确认日志中没有提示使用“默认随机 SECRET_KEY”的警告。
3. **微信扫码登录**：在前端设置页或聊天页面尝试触发微信扫码（若启用该功能），验证登录及配置加载链路。
4. **计费模块检查**：进入计费仪表盘，确认数据展示及相关图表无异常报错（验证外键与表结构是否正确关联）。
5. **技能加载测试**：确认预置技能及扩展插件可以被正常解析和加载。

## 5. 故障回滚方案

如果在上线过程中出现严重阻碍性问题（如数据库迁移失败或启动异常）：
1. **停止服务**：停止后端的 FastAPI 进程。
2. **恢复数据库**：将第 1 步中备份的 `openawa.db` 覆盖当前出错的数据库。
3. **代码回退**：将代码库（前端与后端）回退到上一稳定版本的 Git 标签。
4. **重新启动**：重启后端服务，恢复到迁移前状态。
