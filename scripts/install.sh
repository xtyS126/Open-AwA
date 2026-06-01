#!/usr/bin/env bash
# ================================================================
# Open-AwA 一键安装脚本 (Linux / macOS)
#
# 用法:
#   curl -fsSL https://.../install.sh | bash
#   或
#   bash install.sh
#
# 自动检测环境、安装 Python/Node.js 依赖、构建前端、初始化配置。
# ================================================================

set -euo pipefail

# ---- 颜色输出 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERR]${NC} $*"; }

# ---- 检测系统 ----
detect_os() {
    case "$(uname -s)" in
        Darwin) OS="macos" ;;
        Linux)  OS="linux" ;;
        *)      err "不支持的操作系统: $(uname -s)"; exit 1 ;;
    esac
    info "检测到操作系统: ${OS}"
}

# ---- 检查 Python ----
check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON="python3"
    elif command -v python &>/dev/null; then
        PYTHON="python"
    else
        err "未找到 Python，请先安装 Python 3.11+"
        info "安装方法: https://www.python.org/downloads/"
        exit 1
    fi

    local version
    version=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local major minor
    major=$($PYTHON -c "import sys; print(sys.version_info.major)")
    minor=$($PYTHON -c "import sys; print(sys.version_info.minor)")

    if [ "$major" -lt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -lt 11 ]); then
        err "Python 版本过低: ${version}，需要 3.11+"
        exit 1
    fi
    ok "Python ${version}"
}

# ---- 检查 Node.js ----
check_node() {
    if command -v node &>/dev/null; then
        local version
        version=$(node --version)
        local major
        major=$(echo "$version" | sed 's/v//' | cut -d. -f1)
        if [ "$major" -lt 18 ]; then
            warn "Node.js 版本较低 (${version})，建议升级到 18+"
        else
            ok "Node.js ${version}"
        fi
    else
        warn "未找到 Node.js，将跳过前端构建（仅后端服务可用）"
        HAS_NODE=false
        return
    fi
    HAS_NODE=true
}

# ---- 检查 pip ----
check_pip() {
    if ! $PYTHON -m pip --version &>/dev/null; then
        err "pip 不可用，请先安装 pip"
        exit 1
    fi
    ok "pip 可用"
}

# ---- 设置项目目录 ----
setup_dirs() {
    INSTALL_DIR="${INSTALL_DIR:-$HOME/.openawa}"
    info "安装目录: ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}" "${INSTALL_DIR}/data" "${INSTALL_DIR}/logs"

    # 如果脚本在项目目录中运行，使用本地代码；否则从 GitHub 克隆
    if [ -f "../pyproject.toml" ] && [ -d "../backend" ]; then
        PROJECT_DIR="$(cd .. && pwd)"
        info "检测到本地项目目录: ${PROJECT_DIR}"
    elif [ -d "./backend" ] && [ -f "./pyproject.toml" ]; then
        PROJECT_DIR="$(pwd)"
        info "使用当前目录作为项目目录: ${PROJECT_DIR}"
    else
        info "克隆 Open-AwA 仓库..."
        PROJECT_DIR="${INSTALL_DIR}/src"
        if [ -d "${PROJECT_DIR}" ]; then
            info "更新已有仓库..."
            (cd "${PROJECT_DIR}" && git pull --ff-only) || true
        else
            git clone https://github.com/open-awa/open-awa.git "${PROJECT_DIR}" 2>/dev/null || {
                warn "无法克隆仓库，请手动下载并指定 PROJECT_DIR"
                exit 1
            }
        fi
    fi
}

# ---- 安装后端依赖 ----
install_backend() {
    info "安装 Python 依赖..."
    cd "${PROJECT_DIR}"

    # 创建虚拟环境
    if [ ! -d ".venv" ]; then
        $PYTHON -m venv .venv
        ok "创建虚拟环境"
    fi
    source .venv/bin/activate

    # 安装依赖
    pip install -q --upgrade pip
    pip install -q -r backend/requirements.txt
    pip install -q -e . --no-deps 2>/dev/null || true
    ok "后端依赖安装完成"
}

# ---- 构建前端 ----
build_frontend() {
    if [ "${HAS_NODE:-true}" = false ]; then
        warn "跳过前端构建（Node.js 不可用）"
        return
    fi

    info "构建前端..."
    cd "${PROJECT_DIR}/frontend"

    if [ ! -d "node_modules" ]; then
        info "安装前端依赖..."
        npm install --silent
    fi

    npm run build
    ok "前端构建完成"
    cd "${PROJECT_DIR}"
}

# ---- 初始化配置 ----
init_config() {
    info "初始化配置..."

    # 生成 SECRET_KEY（如果未设置）
    if [ -z "${SECRET_KEY:-}" ]; then
        SECRET_KEY=$($PYTHON -c "import secrets; print(secrets.token_urlsafe(32))")
    fi

    # 创建 .env 文件
    cat > "${INSTALL_DIR}/.env" <<EOF
# Open-AwA 配置文件（由安装脚本自动生成）
ENVIRONMENT=production
SECRET_KEY=${SECRET_KEY}
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
DATABASE_URL=sqlite:///${INSTALL_DIR}/data/openawa.db
VECTOR_DB_PATH=${INSTALL_DIR}/data/vector_db
LOG_DIR=${INSTALL_DIR}/logs
EOF

    ok "配置文件已创建: ${INSTALL_DIR}/.env"

    # 初始化数据库
    info "初始化数据库..."
    cd "${PROJECT_DIR}"
    source .venv/bin/activate 2>/dev/null || true
    $PYTHON -m openawa.cli.main migrate 2>/dev/null || {
        # 如果 CLI 不可用，直接用 Python 初始化
        $PYTHON -c "
import sys
sys.path.insert(0, 'backend')
from db.models import init_db
init_db()
" 2>/dev/null || warn "数据库初始化跳过（将在首次启动时自动完成）"
    }
    ok "数据库初始化完成"
}

# ---- 提示最终信息 ----
show_final() {
    echo
    echo "================================================================"
    echo "  Open-AwA 安装完成"
    echo "================================================================"
    echo
    echo "  安装目录:  ${INSTALL_DIR}"
    echo "  项目目录:  ${PROJECT_DIR}"
    echo
    echo "  启动服务:"
    echo "    cd ${PROJECT_DIR}"
    echo "    source .venv/bin/activate"
    echo "    openawa serve --host 0.0.0.0 --port 8000"
    echo
    echo "  后台常驻:"
    echo "    openawa serve --host 0.0.0.0 --port 8000 --daemon"
    echo
    echo "  配置模型 API Key:"
    echo "    编辑 ${INSTALL_DIR}/.env，设置 DASHSCOPE_API_KEY 等"
    echo
    echo "  管理命令:"
    echo "    openawa doctor          # 系统诊断"
    echo "    openawa user create     # 创建用户"
    echo "    openawa user list       # 列出用户"
    echo
    echo "  浏览器打开: http://localhost:8000"
    echo
    echo "================================================================"
}

# ---- 主流程 ----
main() {
    echo "================================================================"
    echo "  Open-AwA 一键安装"
    echo "================================================================"
    echo

    detect_os
    check_python
    check_node
    check_pip
    setup_dirs
    install_backend
    build_frontend
    init_config
    show_final
}

main "$@"
