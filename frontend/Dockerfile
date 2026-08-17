# Open-AwA 前端 Dockerfile
# 多阶段构建：Node 编译 -> Nginx 运行时
# 设计原则：层缓存友好、非 root 用户、最小运行时镜像

# ---- 阶段 1：前端构建 ----
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# 利用 Docker 缓存层：先复制依赖文件
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --production=false 2>/dev/null || npm install

# 复制前端源码并构建
COPY frontend/ ./
RUN npm run build

# ---- 阶段 2：Nginx 运行时 ----
FROM nginx:1.27-alpine AS frontend

# 镜像元数据
LABEL org.opencontainers.image.title="Open-AwA Frontend" \
      org.opencontainers.image.description="Open-AwA 前端服务（Nginx + 静态资源 + 反向代理）" \
      org.opencontainers.image.source="https://github.com/Open-AwA/Open-AwA" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="nginx:1.27-alpine"

# 安装 curl（健康检查）与 openssl（init-ssl.sh 生成自签证书）
RUN apk add --no-cache curl openssl \
    && rm -rf /var/cache/apk/*

# 复制前端构建产物（从 builder 阶段，无需宿主机预构建）
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html

# 复制 nginx 配置（基础版 HTTP/2 + 自签 SSL，开发/测试环境用）
# 生产环境由 docker-compose.prod.yml 挂载 ssl.conf 覆盖
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

# 创建非 root 用户运行的 nginx pid 目录与日志目录
# nginx 默认以 root 启动 master 进程，worker 以 nginx 用户运行
# 这里保持 nginx 默认行为，因为 master 需要 80 端口权限
# 健康检查走 80 端口，无需切换用户
RUN mkdir -p /var/run/nginx /var/log/nginx \
    && chown -R nginx:nginx /var/run/nginx /var/log/nginx /usr/share/nginx/html /etc/nginx/conf.d

# 容器内健康检查（80 端口 /healthz 端点，nginx 配置中已对该端点例外不重定向）
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:80/healthz || exit 1

# 暴露 80（重定向到 443）与 443（HTTP/2 + SSL 主服务）
EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]
