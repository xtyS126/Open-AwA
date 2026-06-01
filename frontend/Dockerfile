# ---- Nginx 前端服务 ----
FROM nginx:alpine

# 复制前端构建产物（需先在宿主机构建：npm run build）
COPY frontend/dist /usr/share/nginx/html

# Nginx 配置文件
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:80/ || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
