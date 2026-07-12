#!/bin/sh
# 后端容器启动入口脚本
# 职责：
#   1. 自动生成缺失的密钥与配置（首次部署零配置）
#   2. 运行 Alembic 数据库迁移（升级到最新版本）
#   3. 启动 uvicorn 服务
# 设计原则：保持幂等，容器重启不产生副作用
# 系统初始化（创建 owner 用户）由前端引导页面完成，本脚本不自动调用 init API

set -e

# 切换到后端工作目录
cd /app/backend

# ============================================================================
# 步骤 1：自动生成缺失的密钥与配置（零配置启动）
# ============================================================================
# 持久化到 /app/data/.env.local，容器重启不丢失
ENV_LOCAL_FILE="/app/data/.env.local"
ENV_LOCAL_NEW=""
NEED_PERSIST=false

# 辅助函数：检查环境变量是否缺失或为占位符
_env_missing() {
    val=$(eval echo "\$$1")
    [ -z "$val" ] || [ "$val" = "changeme" ] || [ "$val" = "your-secret-key-here" ]
}

# 辅助函数：通过 Python 生成密钥
_gen_jwt_key() {
    python -c "import secrets; print(secrets.token_urlsafe(48))"
}
_gen_csrf_key() {
    python -c "import secrets; print(secrets.token_urlsafe(48))"
}
_gen_enc_key() {
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
}
_gen_api_key() {
    python -c "import secrets; print('sk-' + secrets.token_urlsafe(32))"
}

# JWT_SECRET_KEY
if _env_missing JWT_SECRET_KEY; then
    JWT_SECRET_KEY=$(_gen_jwt_key)
    ENV_LOCAL_NEW="${ENV_LOCAL_NEW}JWT_SECRET_KEY=${JWT_SECRET_KEY}\n"
    NEED_PERSIST=true
    echo "[INFO] 自动生成 JWT_SECRET_KEY"
fi

# CSRF_SECRET_KEY
if _env_missing CSRF_SECRET_KEY; then
    CSRF_KEY=$(_gen_csrf_key)
    ENV_LOCAL_NEW="${ENV_LOCAL_NEW}CSRF_SECRET_KEY=${CSRF_KEY}\n"
    NEED_PERSIST=true
    echo "[INFO] 自动生成 CSRF_SECRET_KEY"
fi

# ENCRYPTION_KEY（必须是合法的 Fernet 密钥）
if _env_missing ENCRYPTION_KEY; then
    ENC_KEY=$(_gen_enc_key)
    ENV_LOCAL_NEW="${ENV_LOCAL_NEW}ENCRYPTION_KEY=${ENC_KEY}\n"
    NEED_PERSIST=true
    echo "[INFO] 自动生成 ENCRYPTION_KEY"
fi

# OPENAWA_API_KEY
if _env_missing OPENAWA_API_KEY; then
    API_KEY=$(_gen_api_key)
    ENV_LOCAL_NEW="${ENV_LOCAL_NEW}OPENAWA_API_KEY=${API_KEY}\n"
    NEED_PERSIST=true
    echo "[INFO] 自动生成 OPENAWA_API_KEY"
fi

# 导出新变量到当前进程，供后续步骤与 uvicorn 使用
[ -n "$JWT_SECRET_KEY" ] && export JWT_SECRET_KEY
[ -n "$CSRF_KEY" ] && export CSRF_SECRET_KEY="$CSRF_KEY"
[ -n "$ENC_KEY" ] && export ENCRYPTION_KEY="$ENC_KEY"
[ -n "$API_KEY" ] && export OPENAWA_API_KEY="$API_KEY"

# 持久化到 .env.local（容器重启不丢失）
if [ "$NEED_PERSIST" = true ]; then
    mkdir -p /app/data
    # 追加而非覆盖，保留用户已有配置
    if [ -f "$ENV_LOCAL_FILE" ]; then
        printf "%b" "$ENV_LOCAL_NEW" >> "$ENV_LOCAL_FILE"
    else
        printf "%b" "$ENV_LOCAL_NEW" > "$ENV_LOCAL_FILE"
    fi
    chmod 600 "$ENV_LOCAL_FILE" 2>/dev/null || true
    echo "[INFO] 新密钥已持久化到 $ENV_LOCAL_FILE"
fi

# 生产环境额外校验密钥强度（development 跳过）
if [ "$ENVIRONMENT" = "production" ] || [ "$ENVIRONMENT" = "prod" ]; then
    for key_var in JWT_SECRET_KEY CSRF_SECRET_KEY ENCRYPTION_KEY; do
        key_val=$(eval echo "\$$key_var")
        key_len=${#key_val}
        if [ "$key_len" -lt 32 ]; then
            echo "[FATAL] $key_var 长度 ($key_len) 不足 32 字符" >&2
            exit 1
        fi
    done
    # 校验 ENCRYPTION_KEY 是合法的 Fernet 密钥
    python -c "
from cryptography.fernet import Fernet
import os
key = os.environ.get('ENCRYPTION_KEY', '')
try:
    Fernet(key)
except Exception as e:
    raise SystemExit(f'[FATAL] ENCRYPTION_KEY 不是合法的 Fernet 密钥: {e}')
"
    echo "[INFO] 生产环境密钥校验通过"
fi

# ============================================================================
# 步骤 2：运行 Alembic 数据库迁移（仅当 versions 目录非空时）
# ============================================================================
if [ -d "alembic/versions" ] && [ -n "$(ls -A alembic/versions 2>/dev/null | grep -v '.gitkeep')" ]; then
    echo "[INFO] 运行 Alembic 数据库迁移 (upgrade head)"
    if ! python -m alembic upgrade head; then
        echo "[FATAL] Alembic 迁移失败，容器退出" >&2
        exit 1
    fi
    echo "[INFO] Alembic 迁移完成"
else
    echo "[INFO] 未发现 Alembic 迁移脚本，跳过迁移步骤（首次部署将由 init_db 自动建表）"
fi

# ============================================================================
# 步骤 3：启动 uvicorn 服务（主进程）
# ============================================================================
# 系统初始化（创建 owner 用户）由前端引导页面完成：
#   1. 用户首次访问网站时，前端调用 GET /api/system/init-status 检测
#   2. 未初始化则自动跳转到 /setup 引导页
#   3. 用户填写用户名/密码后前端调 POST /api/system/init 完成
#   4. 完成后跳转登录页
# 本脚本仅负责启动 uvicorn，不自动调用 init API
echo "[INFO] 启动 uvicorn 服务，监听 ${BACKEND_HOST:-0.0.0.0}:${BACKEND_PORT:-8000}"
echo "[INFO] 若首次部署，请通过浏览器访问 http://<宿主机IP>:${BACKEND_PORT:-8000} 完成初始化"
exec python -m uvicorn main:app --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT:-8000}"
