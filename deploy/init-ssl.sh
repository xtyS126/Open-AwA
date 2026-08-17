#!/bin/sh
# 自签证书生成脚本（用于 nginx HTTP/2 启用）
# 适用场景：开发/测试环境，浏览器需手动信任自签证书
# 生产环境请使用 deploy/init-ssl-letsencrypt.sh 申请 Let's Encrypt 证书
#
# 运行位置：nginx 容器内部（由 docker-compose.yml 的 command 调用）
# 证书输出：/etc/nginx/ssl/nginx.crt 与 /etc/nginx/ssl/nginx.key
#          （宿主机对应 deploy/ssl/nginx.crt 与 deploy/ssl/nginx.key）
#
# 幂等：证书已存在时跳过生成

set -e

SSL_DIR="/etc/nginx/ssl"
CERT_FILE="$SSL_DIR/nginx.crt"
KEY_FILE="$SSL_DIR/nginx.key"

# 证书已存在则跳过
if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "[DONE] SSL 证书已存在，跳过生成: $CERT_FILE"
    exit 0
fi

mkdir -p "$SSL_DIR"

# 生成自签证书（含 SAN: localhost + 127.0.0.1）
# -x509: 直接输出自签证书而非 CSR
# -nodes: 不加密私钥（nginx 启动时无需输入密码）
# -days 365: 证书有效期 1 年
# -addext: 添加 SAN 扩展，覆盖 localhost 与 127.0.0.1
openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/C=CN/ST=Local/L=Local/O=Open-AwA/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# 限制私钥权限，防止其他用户读取
chmod 600 "$KEY_FILE"

echo "[DONE] SSL 证书已生成: $CERT_FILE"
