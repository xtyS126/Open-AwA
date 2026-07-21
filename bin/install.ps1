<#
.SYNOPSIS
    Open-AwA 一键安装脚本 (Windows PowerShell)

.DESCRIPTION
    自动检测环境、安装 Python/Node.js 依赖、构建前端、初始化配置。

.PARAMETER InstallDir
    安装目录，默认为 $HOME\.openawa

.PARAMETER ProjectDir
    项目源码目录（本地开发模式使用）

.PARAMETER SkipFrontend
    跳过前端构建

.EXAMPLE
    irm https://.../install.ps1 | iex

.EXAMPLE
    .\bin\install.ps1 -InstallDir "D:\openawa" -SkipFrontend
#>

param(
    [string]$InstallDir = "$env:USERPROFILE\.openawa",
    [string]$ProjectDir = "",
    [switch]$SkipFrontend = $false
)

$ErrorActionPreference = "Stop"

# ---- 颜色输出 ----
function Write-Info  { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Write-OK    { Write-Host "[OK]   $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ERR]  $args" -ForegroundColor Red }

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Open-AwA 一键安装 (Windows)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ---- 检测 Python ----
Write-Info "检测 Python..."
try {
    $pythonVersion = python --version 2>&1
    Write-OK $pythonVersion
} catch {
    Write-Err "未找到 Python，请先安装 Python 3.11+"
    Write-Info "下载地址: https://www.python.org/downloads/"
    exit 1
}

# ---- 检测 Node.js ----
$hasNode = $true
Write-Info "检测 Node.js..."
try {
    $nodeVersion = node --version 2>&1
    Write-OK "Node.js $nodeVersion"
} catch {
    Write-Warn "未找到 Node.js，将跳过前端构建"
    $hasNode = $false
}

# ---- 检测 pip ----
Write-Info "检测 pip..."
try {
    $pipVersion = python -m pip --version 2>&1
    Write-OK "pip 可用"
} catch {
    Write-Err "pip 不可用，请先安装 pip"
    exit 1
}

# ---- 确定项目目录 ----
if ($ProjectDir) {
    Write-Info "使用指定项目目录: $ProjectDir"
} elseif (Test-Path "..\pyproject.toml") {
    $ProjectDir = (Resolve-Path "..").Path
    Write-Info "检测到本地项目目录: $ProjectDir"
} elseif (Test-Path ".\pyproject.toml") {
    $ProjectDir = (Get-Location).Path
    Write-Info "使用当前目录: $ProjectDir"
} else {
    Write-Info "克隆 Open-AwA 仓库..."
    $ProjectDir = "$InstallDir\src"
    if (Test-Path $ProjectDir) {
        Write-Info "更新已有仓库..."
        Push-Location $ProjectDir
        try { git pull --ff-only 2>$null } catch {}
        Pop-Location
    } else {
        git clone https://github.com/open-awa/open-awa.git $ProjectDir 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "无法克隆仓库，请手动下载 Open-AwA 并指定 -ProjectDir"
            exit 1
        }
    }
}

# ---- 创建目录 ----
Write-Info "创建安装目录..."
New-Item -ItemType Directory -Force -Path $InstallDir, "$InstallDir\data", "$InstallDir\logs" | Out-Null
Write-OK "安装目录: $InstallDir"

# ---- 创建虚拟环境 ----
Write-Info "创建 Python 虚拟环境..."
$venvPath = "$ProjectDir\.venv"
if (-not (Test-Path $venvPath)) {
    python -m venv $venvPath
    Write-OK "虚拟环境已创建"
} else {
    Write-OK "虚拟环境已存在"
}

# ---- 激活虚拟环境并安装依赖 ----
Write-Info "安装 Python 依赖..."
$activateScript = "$venvPath\Scripts\Activate.ps1"
. $activateScript
python -m pip install -q --upgrade pip
pip install -q -r "$ProjectDir\lib\backend\requirements.txt"
try {
    pip install -q -e $ProjectDir --no-deps 2>$null
} catch {}
Write-OK "后端依赖安装完成"

# ---- 构建前端 ----
if (-not $SkipFrontend -and $hasNode) {
    Write-Info "构建前端..."
    $frontendDir = "$ProjectDir\lib\frontend"
    if (-not (Test-Path "$frontendDir\node_modules")) {
        Write-Info "安装前端依赖..."
        Push-Location $frontendDir
        npm install --silent
        Pop-Location
    }
    Push-Location $frontendDir
    npm run build
    Pop-Location
    Write-OK "前端构建完成"
} elseif ($SkipFrontend) {
    Write-Warn "跳过前端构建（--SkipFrontend）"
}

# ---- 初始化配置 ----
Write-Info "初始化配置..."
$jwtSecretKey = if ($env:JWT_SECRET_KEY) { $env:JWT_SECRET_KEY } else { python -c "import secrets; print(secrets.token_urlsafe(64))" }
$csrfSecretKey = if ($env:CSRF_SECRET_KEY) { $env:CSRF_SECRET_KEY } else { python -c "import secrets; print(secrets.token_urlsafe(64))" }
$encryptionKey = if ($env:ENCRYPTION_KEY) { $env:ENCRYPTION_KEY } else { python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" }
$openawaApiKey = if ($env:OPENAWA_API_KEY) { $env:OPENAWA_API_KEY } else { python -c "import secrets; print(secrets.token_urlsafe(48))" }
$ownerPassword = if ($env:OPENAWA_OWNER_PASSWORD) { $env:OPENAWA_OWNER_PASSWORD } else { python -c "import secrets; print(secrets.token_urlsafe(24))" }

$envContent = @"
# Open-AwA 配置文件（由安装脚本自动生成）
ENVIRONMENT=production
JWT_SECRET_KEY=$jwtSecretKey
CSRF_SECRET_KEY=$csrfSecretKey
ENCRYPTION_KEY=$encryptionKey
OPENAWA_API_KEY=$openawaApiKey
OPENAWA_OWNER_PASSWORD=$ownerPassword
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
DATABASE_URL=sqlite:///$InstallDir/data/openawa.db
VECTOR_DB_PATH=$InstallDir/data/vector_db
LOG_DIR=$InstallDir/logs
"@
$envContent | Out-File -FilePath "$InstallDir\.env" -Encoding UTF8
Write-OK "配置文件已创建: $InstallDir\.env"

# ---- 初始化数据库 ----
Write-Info "初始化数据库..."
try {
    Push-Location $ProjectDir
    python -m openawa.cli.main migrate 2>$null
    if ($LASTEXITCODE -ne 0) {
        # CLI 不可用时直接用 Python 初始化
        python -c @"
import sys; sys.path.insert(0, 'lib/backend')
from db.models import init_db
init_db()
print('数据库初始化完成')
"@ 2>$null
    }
    Pop-Location
    Write-OK "数据库初始化完成"
} catch {
    Write-Warn "数据库初始化跳过（将在首次启动时自动完成）"
}

# ---- 最终信息 ----
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Open-AwA 安装完成" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  安装目录:  $InstallDir"
Write-Host "  项目目录:  $ProjectDir"
Write-Host ""
Write-Host "  启动服务:"
Write-Host "    cd $ProjectDir"
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    openawa serve --host 0.0.0.0 --port 8000"
Write-Host ""
Write-Host "  后台常驻:"
Write-Host "    openawa serve --host 0.0.0.0 --port 8000 --daemon"
Write-Host ""
Write-Host "  配置模型 API Key:"
Write-Host "    编辑 $InstallDir\.env，设置 DASHSCOPE_API_KEY 等"
Write-Host ""
Write-Host "  管理命令:"
Write-Host "    openawa doctor          # 系统诊断"
Write-Host "    openawa user create     # 创建用户"
Write-Host "    openawa user list       # 列出用户"
Write-Host ""
Write-Host "  浏览器打开: http://localhost:8000"
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
