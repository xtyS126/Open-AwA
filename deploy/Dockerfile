# Open-AwA 后端 Dockerfile
# 多阶段构建：前端编译 -> 后端运行时
# 设计原则：层缓存友好、非 root 用户、最小运行时镜像

# ---- 阶段 1：前端构建 ----
FROM node:20-alpine AS frontend-builder

WORKDIR /app/lib/frontend

# 利用 Docker 缓存层：先复制依赖文件
COPY lib/frontend/package.json lib/frontend/package-lock.json* ./
RUN npm ci --production=false 2>/dev/null || npm install

# 复制前端源码并构建
COPY lib/frontend/ ./
RUN npm run build

# ---- 阶段 2：后端依赖安装（独立层，便于缓存） ----
FROM python:3.12-slim AS backend-deps

WORKDIR /app

# 安装系统依赖（curl 仅用于健康检查）
# tini 作为 PID 1 init 系统，正确处理信号转发与僵尸进程回收
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY lib/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# ---- 阶段 3：后端运行时（最终镜像） ----
FROM backend-deps AS backend

# 镜像元数据，便于长期维护与追踪
LABEL org.opencontainers.image.title="Open-AwA Backend" \
      org.opencontainers.image.description="Open-AwA AI Agent 后端服务（FastAPI + Uvicorn）" \
      org.opencontainers.image.source="https://github.com/Open-AwA/Open-AwA" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="python:3.12-slim"

WORKDIR /app

# 创建非 root 用户与运行时数据目录
# 使用固定 UID/GID 1000，便于宿主机卷权限对齐
# 运行时数据目录统一在 /app/var/ 下（与项目根 var/ 结构对齐）
RUN groupadd --system --gid 1000 openawa \
    && useradd --system --uid 1000 --gid openawa --create-home --shell /sbin/nologin openawa \
    && mkdir -p /app/var/data /app/var/logs /app/var/workspace /app/var/plugins /app/var/pets \
    && chown -R openawa:openawa /app

# 复制后端代码与项目元数据
COPY --chown=openawa:openawa lib/backend/ /app/lib/backend/
COPY --chown=openawa:openawa pyproject.toml /app/

# 安装 openawa 包（开发模式，便于依赖解析与版本约束）
RUN pip install --no-cache-dir -e /app/

# 复制前端构建产物
COPY --chown=openawa:openawa --from=frontend-builder /app/lib/frontend/dist /app/lib/frontend/dist

# 复制入口脚本并赋权
COPY --chown=openawa:openawa deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 切换到非 root 用户
USER openawa

# 生产环境变量（容器内路径结构 /app/var/* 与项目根 var/ 对齐）
ENV ENVIRONMENT=production \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_DIR=/app/var/logs \
    DATABASE_URL=sqlite:////app/var/data/openawa.db \
    VECTOR_DB_PATH=/app/var/data/qdrant \
    DATA_DIR=/app/var/data

# 容器内健康检查（30 秒间隔，10 秒超时，启动期 60 秒给首次初始化留时间）
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/system/ping || exit 1

EXPOSE 8000

# 入口脚本完成密钥自动生成 + Alembic 迁移 + 首次初始化 + 启动 uvicorn
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
# CMD 留空：entrypoint.sh 内部已 exec uvicorn 作为主进程
