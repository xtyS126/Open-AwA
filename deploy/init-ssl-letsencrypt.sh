#!/bin/sh
# SSL 证书首次申请脚本（Let's Encrypt 生产版）
# 此脚本于 2026-08-12 从 deploy/init-ssl.sh 迁移而来：
#   原始 init-ssl.sh 已改为自签证书版本（供开发/测试环境启用 HTTP/2），
#   生产环境 Let's Encrypt 证书申请流程保留在此文件中。
#
# 用法：
#   bash deploy/init-ssl-letsencrypt.sh
#
# 前置条件：
#   1. 已在 .env 中设置 DOMAIN 和 EMAIL
#   2. DOMAIN 的 DNS A 记录已指向本机公网 IP
#   3. 已运行：docker compose -f docker-compose.yml -f docker-compose.prod.yml build
#
# 流程：
#   1. 创建 letsencrypt 与 webroot 卷
#   2. 启动临时 nginx（仅 80 端口，提供 webroot challenge 响应）
#   3. 运行 certbot 申请证书
#   4. 关闭临时 nginx，下次启动将自动加载 ssl.conf
#
# 此脚本幂等，已申请过的证书可重复运行（certbot 会跳过）

set -e

# 加载 .env
if [ ! -f .env ]; then
    echo "[FATAL] 未找到 .env 文件，请先 cp .env.example .env 并填写" >&2
    exit 1
fi

# shellcheck disable=SC1091
set -a
. ./.env
set +a

# 校验必填项
if [ -z "$DOMAIN" ]; then
    echo "[FATAL] .env 中未设置 DOMAIN" >&2
    exit 1
fi
if [ -z "$EMAIL" ]; then
    echo "[FATAL] .env 中未设置 EMAIL（Let's Encrypt 注册邮箱）" >&2
    exit 1
fi

echo "[INFO] 开始为 $DOMAIN 申请 Let's Encrypt 证书"

# 创建 letsencrypt 与 webroot 卷（幂等）
docker volume create openawa-certbot-letsencrypt >/dev/null 2>&1 || true
docker volume create openawa-certbot-webroot >/dev/null 2>&1 || true

# 启动临时 nginx 提供挑战响应
# nginx 配置：仅监听 80，提供 /.well-known/acme-challenge/ 静态文件服务
echo "[INFO] 启动临时 nginx（80 端口，仅响应 ACME challenge）"
cat > /tmp/nginx-acme.conf <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
    }
    location / {
        return 200 "等待 SSL 证书申请...\\n";
        add_header Content-Type text/plain;
    }
}
EOF

# 清理可能存在的临时容器
docker rm -f openawa-nginx-acme 2>/dev/null || true

# 启动临时 nginx 容器
docker run -d --rm \
    --name openawa-nginx-acme \
    --network openawa-net \
    -p 80:80 \
    -v openawa-certbot-webroot:/var/www/certbot:ro \
    -v /tmp/nginx-acme.conf:/etc/nginx/conf.d/default.conf:ro \
    nginx:1.27-alpine

# 等待 nginx 就绪
echo "[INFO] 等待 nginx 启动..."
sleep 3

# 运行 certbot 申请证书
echo "[INFO] 运行 certbot 申请证书（域名：$DOMAIN，邮箱：$EMAIL）"
docker run --rm \
    --name openawa-certbot-init \
    --network openawa-net \
    -v openawa-certbot-letsencrypt:/etc/letsencrypt \
    -v openawa-certbot-webroot:/var/www/certbot \
    certbot/certbot:latest \
    certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    --non-interactive \
    --keep-until-expiring

# 停止临时 nginx
echo "[INFO] 关闭临时 nginx"
docker stop openawa-nginx-acme 2>/dev/null || true

echo ""
echo "[DONE] SSL 证书申请完成"
echo ""
echo "证书存储位置：openawa-certbot-letsencrypt 卷"
echo "  实际路径：/etc/letsencrypt/live/$DOMAIN/"
echo ""
echo "下一步：启动生产服务（自动加载 SSL 配置）"
echo "  docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d"
