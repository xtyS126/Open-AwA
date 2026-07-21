#!/bin/bash
# Open-AwA Docker 一键部署脚本 (Linux/macOS Bash)
#
# 用法：
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh                       # 默认 dev 模式
#   ./scripts/deploy.sh full                  # 后端 + 前端
#   ./scripts/deploy.sh prod                  # 生产 HTTPS（需先配置 DOMAIN）
#   ./scripts/deploy.sh postgres              # 启用 PostgreSQL
#   ./scripts/deploy.sh --user admin --pass "MyStrong1Pass" --mode full
#
# 选项：
#   -m|--mode    dev|full|prod|postgres       部署模式（默认 dev）
#   -u|--user    admin                         owner 用户名（默认 admin）
#   -p|--pass    xxxxx                         owner 密码（留空随机生成）
#   -f|--force                                覆盖已有 .env 并重新初始化

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# ---- 颜色输出 ----
info()  { echo -e "\033[34m[INFO]\033[0m $*"; }
ok()    { echo -e "\033[32m[OK]\033[0m $*"; }
warn()  { echo -e "\033[33m[WARN]\033[0m $*"; }
err()   { echo -e "\033[31m[ERR]\033[0m $*" >&2; }
step()  { echo -e "\n\033[36m=== $* ===\033[0m"; }

# ---- 参数解析 ----
MODE="dev"
ADMIN_USER="admin"
ADMIN_PASS=""
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--mode)   MODE="$2"; shift 2 ;;
        -u|--user)   ADMIN_USER="$2"; shift 2 ;;
        -p|--pass)   ADMIN_PASS="$2"; shift 2 ;;
        -f|--force)  FORCE=true; shift ;;
        dev|full|prod|postgres) MODE="$1"; shift ;;
        *)
            echo "未知参数: $1"
            echo "用法: $0 [--mode dev|full|prod|postgres] [--user admin] [--pass xxx] [--force]"
            exit 1
            ;;
    esac
done

echo "================================================================"
echo "  Open-AwA Docker 一键部署 (Mode: $MODE)"
echo "================================================================"

# ============================================================================
# 1. 环境检测
# ============================================================================
step "步骤 1/5: 环境检测"

info "检测 Docker..."
if ! docker version >/dev/null 2>&1; then
    err "未检测到 Docker，请先安装"
    info "下载地址: https://docs.docker.com/get-docker/"
    exit 1
fi
ok "Docker 已安装"

info "检测 Docker Compose..."
if ! docker compose version >/dev/null 2>&1; then
    err "未检测到 Docker Compose v2，请升级 Docker"
    exit 1
fi
ok "Docker Compose v2"

ok "项目目录: $PROJECT_ROOT"

# ============================================================================
# 2. 自动生成 .env
# ============================================================================
step "步骤 2/5: 生成配置文件 (.env)"

ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

if [[ -f "$ENV_FILE" ]] && [[ "$FORCE" == "false" ]]; then
    ok ".env 已存在，跳过生成（如需重新生成请加 --force）"
    SKIP_ENV_GEN=true
else
    if [[ -f "$ENV_FILE" ]] && [[ "$FORCE" == "true" ]]; then
        warn "已存在 .env，因 --force 参数将覆盖"
        rm -f "$ENV_FILE"
    fi
    SKIP_ENV_GEN=false
fi

if [[ "$SKIP_ENV_GEN" == "false" ]]; then
    info "从模板创建 .env..."
    cp "$ENV_EXAMPLE" "$ENV_FILE"

    # 检查 Python + cryptography
    if ! python3 -c "from cryptography.fernet import Fernet" >/dev/null 2>&1; then
        err "需要 Python3 + cryptography 库"
        info "可运行: pip3 install cryptography"
        exit 1
    fi

    info "生成三密钥..."
    JWT_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    CSRF_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    ENC_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    API_KEY="sk-$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"

    sed -i.bak "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_KEY|" "$ENV_FILE"
    sed -i.bak "s|^CSRF_SECRET_KEY=.*|CSRF_SECRET_KEY=$CSRF_KEY|" "$ENV_FILE"
    sed -i.bak "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENC_KEY|" "$ENV_FILE"
    sed -i.bak "s|^OPENAWA_API_KEY=.*|OPENAWA_API_KEY=$API_KEY|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"

    ok ".env 已生成（含三密钥 + API Key）"
fi

# ============================================================================
# 3. 构建并启动容器
# ============================================================================
step "步骤 3/5: 构建并启动容器"

COMPOSE_ARGS=(--env-file .env)

case "$MODE" in
    dev)
        COMPOSE_FILES=()
        PROFILE_ARGS=()
        ;;
    full)
        COMPOSE_FILES=()
        PROFILE_ARGS=(--profile frontend)
        ;;
    prod)
        COMPOSE_FILES=(-f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml)
        PROFILE_ARGS=()
        info "生产模式需要 DOMAIN 环境变量，请在 .env 中配置后重新运行"
        info "首次申请 SSL 证书: bash deploy/init-ssl.sh"
        ;;
    postgres)
        COMPOSE_FILES=(-f deploy/docker-compose.yml -f deploy/docker-compose.postgres.yml)
        PROFILE_ARGS=()
        ;;
esac

info "构建镜像（首次约 5-10 分钟）..."
docker compose "${COMPOSE_ARGS[@]}" "${COMPOSE_FILES[@]}" build
ok "镜像构建完成"

info "启动容器..."
docker compose "${COMPOSE_ARGS[@]}" "${COMPOSE_FILES[@]}" "${PROFILE_ARGS[@]}" up -d
ok "容器已启动"

# ============================================================================
# 4. 等待后端健康
# ============================================================================
step "步骤 4/5: 等待后端就绪"

info "等待后端健康检查通过（最多 90 秒）..."
HEALTHY=false
for i in $(seq 1 30); do
    sleep 3
    if curl -fsS http://localhost:8000/api/system/ping >/dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    echo -n "."
done
echo ""

if [[ "$HEALTHY" == "false" ]]; then
    err "后端未在 90 秒内就绪"
    info "查看日志: docker compose logs backend"
    exit 1
fi
ok "后端已就绪"

# ============================================================================
# 5. 首次部署初始化
# ============================================================================
step "步骤 5/5: 首次部署初始化"

# 检查是否已初始化
SKIP_INIT=false
if STATUS_JSON=$(curl -fsS http://localhost:8000/api/system/init-status 2>/dev/null); then
    INITIALIZED=$(echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('initialized', False))" 2>/dev/null)
    HAS_USERS=$(echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('has_users', False))" 2>/dev/null)
    if [[ "$INITIALIZED" == "True" ]]; then
        ok "系统已初始化，跳过"
        SKIP_INIT=true
    elif [[ "$HAS_USERS" == "True" ]]; then
        ok "数据库已有用户，跳过 init"
        SKIP_INIT=true
    fi
fi

if [[ "$SKIP_INIT" == "false" ]]; then
    # 生成密码（如未提供）
    if [[ -z "$ADMIN_PASS" ]]; then
        ADMIN_PASS="Aw@$(python3 -c "import secrets; print(secrets.token_hex(8))")1"
        ok "已生成随机 owner 密码: $ADMIN_PASS"
    fi

    info "调用 POST /api/system/init 创建 owner..."
    INIT_BODY="{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\",\"nickname\":\"Administrator\"}"

    if INIT_RESP=$(curl -fsS -X POST http://localhost:8000/api/system/init \
        -H "Content-Type: application/json" \
        -d "$INIT_BODY"); then
        ok "初始化完成"
        ok "  用户名: $ADMIN_USER"
        ok "  密码  : $ADMIN_PASS"
    else
        warn "init 端点调用失败"
        info "可手动执行:"
        info "  curl -X POST http://localhost:8000/api/system/init \\"
        info "    -H 'Content-Type: application/json' \\"
        info "    -d '{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}'"
    fi
fi

# ============================================================================
# 完成
# ============================================================================
echo ""
echo "================================================================"
echo -e "\033[32m  部署完成!\033[0m"
echo "================================================================"
echo ""
echo -e "\033[36m访问地址:\033[0m"
echo "  后端 API : http://localhost:8000"
echo "  健康检查  : http://localhost:8000/api/system/ping"
if [[ "$MODE" == "full" ]] || [[ "$MODE" == "prod" ]]; then
    PROTO="http"
    [[ "$MODE" == "prod" ]] && PROTO="https"
    echo "  前端页面  : ${PROTO}://localhost"
fi
echo ""
echo -e "\033[36m登录凭据:\033[0m"
echo "  用户名: $ADMIN_USER"
if [[ -n "$ADMIN_PASS" ]]; then
    echo "  密码  : $ADMIN_PASS"
fi
echo ""
echo -e "\033[36m常用命令:\033[0m"
echo "  docker compose ps                        查看状态"
echo "  docker compose logs -f backend           查看日志"
echo "  docker compose down                      停止"
echo "  docker compose down -v                   停止并删除数据（慎用）"
echo ""
echo -e "\033[36m配置文件位置:\033[0m $ENV_FILE"
