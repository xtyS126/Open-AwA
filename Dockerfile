# ---- 阶段 1：构建前端 ----
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# 利用 Docker 缓存层：先复制依赖文件
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --production=false 2>/dev/null || npm install

# 复制前端源码并构建
COPY frontend/ ./
RUN npm run build

# ---- 阶段 2：后端运行环境 ----
FROM python:3.12-slim AS backend

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制后端代码
COPY backend/ /app/backend/
COPY openawa/ /app/openawa/
COPY pyproject.toml /app/

# 安装 openawa 包（开发模式，使 CLI 可用）
RUN pip install -e /app/

# 复制前端构建产物
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# 创建数据目录
RUN mkdir -p /app/data /app/logs

# 生产环境变量
ENV ENVIRONMENT=production
ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8000
ENV PYTHONUNBUFFERED=1

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/system/ping || exit 1

EXPOSE 8000

# 启动命令
CMD ["python", "-m", "openawa.cli.main", "serve", "--host", "0.0.0.0", "--port", "8000", "--skip-frontend-build"]
