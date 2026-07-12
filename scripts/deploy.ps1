<#
.SYNOPSIS
    Open-AwA Docker 一键部署脚本 (Windows PowerShell)

.DESCRIPTION
    一条命令完成 Docker 部署的全部步骤：
    1. 检测 Docker / Docker Compose
    2. 自动生成 .env（含三密钥 + OPENAWA_API_KEY）
    3. 构建并启动容器
    4. 等待后端健康
    5. 调用 POST /api/system/init 完成首次初始化（创建 owner）
    6. 打印访问地址

.PARAMETER Mode
    部署模式：
    - dev      : 仅后端（HTTP，端口 8000）
    - full     : 后端 + 前端 Nginx 反代（HTTP，80/8000）
    - prod     : 生产模式（HTTPS + Let's Encrypt，需先配置 DOMAIN）
    - postgres : 启用 PostgreSQL 替代 SQLite

.PARAMETER AdminUser
    Owner 用户名，默认 admin

.PARAMETER AdminPassword
    Owner 密码，留空则随机生成并显示

.PARAMETER Force
    覆盖已有 .env 文件并重新初始化

.EXAMPLE
    .\scripts\deploy.ps1
    .\scripts\deploy.ps1 -Mode full
    .\scripts\deploy.ps1 -Mode postgres -AdminUser admin -AdminPassword "MyStrong1Pass"
#>

param(
    [ValidateSet("dev", "full", "prod", "postgres")]
    [string]$Mode = "dev",
    [string]$AdminUser = "admin",
    [string]$AdminPassword = "",
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# ---- 颜色输出 ----
function Write-Info  { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Write-OK    { Write-Host "[OK]   $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ERR]  $args" -ForegroundColor Red }
function Write-Step  { Write-Host "`n=== $args ===" -ForegroundColor Cyan }

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Open-AwA Docker 一键部署 (Mode: $Mode)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# ============================================================================
# 1. 环境检测
# ============================================================================
Write-Step "步骤 1/5: 环境检测"

Write-Info "检测 Docker..."
try {
    $null = docker version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "docker 不可用" }
    Write-OK "Docker 已安装"
} catch {
    Write-Err "未检测到 Docker，请先安装 Docker Desktop"
    Write-Info "下载地址: https://www.docker.com/products/docker-desktop"
    exit 1
}

Write-Info "检测 Docker Compose..."
$composeCmd = $null
try {
    $null = docker compose version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $composeCmd = "docker compose"
        Write-OK "Docker Compose v2"
    }
} catch {}

if (-not $composeCmd) {
    Write-Err "未检测到 Docker Compose，请升级到 Docker Desktop 最新版"
    exit 1
}

Set-Location $ProjectRoot
Write-OK "项目目录: $ProjectRoot"

# ============================================================================
# 2. 自动生成 .env
# ============================================================================
Write-Step "步骤 2/5: 生成配置文件 (.env)"

$envFile = Join-Path $ProjectRoot ".env"
$envExample = Join-Path $ProjectRoot ".env.example"

if (Test-Path $envFile) {
    if ($Force) {
        Write-Warn "已存在 .env，因 -Force 参数将覆盖"
        Remove-Item $envFile -Force
    } else {
        Write-OK ".env 已存在，跳过生成（如需重新生成请加 -Force）"
        $skipEnvGen = $true
    }
}

if (-not $skipEnvGen) {
    Write-Info "从模板创建 .env..."
    Copy-Item $envExample $envFile

    # 生成三密钥
    Write-Info "生成三密钥..."
    $jwtKey = python -c "import secrets; print(secrets.token_urlsafe(48))" 2>$null
    $csrfKey = python -c "import secrets; print(secrets.token_urlsafe(48))" 2>$null
    $encKey = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>$null
    $apiKey = "sk-" + (python -c "import secrets; print(secrets.token_urlsafe(32))" 2>$null)

    if (-not $jwtKey -or -not $csrfKey -or -not $encKey -or -not $apiKey) {
        Write-Err "密钥生成失败，请确认 Python 已安装 cryptography 库"
        Write-Info "可运行: pip install cryptography"
        exit 1
    }

    $envContent = Get-Content $envFile -Raw
    $envContent = $envContent -replace 'JWT_SECRET_KEY=\s*$', "JWT_SECRET_KEY=$jwtKey"
    $envContent = $envContent -replace 'CSRF_SECRET_KEY=\s*$', "CSRF_SECRET_KEY=$csrfKey"
    $envContent = $envContent -replace 'ENCRYPTION_KEY=\s*$', "ENCRYPTION_KEY=$encKey"
    $envContent = $envContent -replace 'OPENAWA_API_KEY=\s*$', "OPENAWA_API_KEY=$apiKey"
    $envContent | Set-Content $envFile -Encoding UTF8

    Write-OK ".env 已生成（含三密钥 + API Key）"
}

# ============================================================================
# 3. 构建并启动容器
# ============================================================================
Write-Step "步骤 3/5: 构建并启动容器"

$composeArgs = @("--env-file", ".env")

switch ($Mode) {
    "dev" {
        $composeFileArgs = @()
        $profileArgs = @()
    }
    "full" {
        $composeFileArgs = @()
        $profileArgs = @("--profile", "frontend")
    }
    "prod" {
        $composeFileArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.prod.yml")
        $profileArgs = @()
        Write-Info "生产模式需要 DOMAIN 环境变量，请在 .env 中配置后重新运行"
        Write-Info "首次申请 SSL 证书: bash docker/init-ssl.sh"
    }
    "postgres" {
        $composeFileArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.postgres.yml")
        $profileArgs = @()
    }
}

Write-Info "构建镜像（首次约 5-10 分钟）..."
$buildArgs = @($composeFileArgs + "build") | Where-Object { $_ }
& docker compose @composeArgs @buildArgs
if ($LASTEXITCODE -ne 0) {
    Write-Err "镜像构建失败"
    exit 1
}
Write-OK "镜像构建完成"

Write-Info "启动容器..."
$upArgs = @($composeFileArgs + $profileArgs + "up", "-d")
& docker compose @composeArgs @upArgs
if ($LASTEXITCODE -ne 0) {
    Write-Err "容器启动失败"
    exit 1
}
Write-OK "容器已启动"

# ============================================================================
# 4. 等待后端健康
# ============================================================================
Write-Step "步骤 4/5: 等待后端就绪"

Write-Info "等待后端健康检查通过（最多 90 秒）..."
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 3
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/system/ping" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
        Write-Host -NoNewline "."
    }
}
Write-Host ""

if (-not $healthy) {
    Write-Err "后端未在 90 秒内就绪"
    Write-Info "查看日志: docker compose logs backend"
    exit 1
}
Write-OK "后端已就绪"

# ============================================================================
# 5. 首次部署初始化
# ============================================================================
Write-Step "步骤 5/5: 首次部署初始化"

# 检查是否已初始化
try {
    $statusResp = Invoke-WebRequest -Uri "http://localhost:8000/api/system/init-status" -TimeoutSec 5 -UseBasicParsing
    $statusData = $statusResp.Content | ConvertFrom-Json
    if ($statusData.data.initialized) {
        Write-OK "系统已初始化，跳过"
        $skipInit = $true
    } elseif ($statusData.data.has_users) {
        Write-OK "数据库已有用户，跳过 init（如需强制重新初始化请使用 -Force 并清空数据卷）"
        $skipInit = $true
    }
} catch {
    Write-Warn "无法查询初始化状态，继续尝试 init"
}

if (-not $skipInit) {
    # 生成密码（如未提供）
    if (-not $AdminPassword) {
        $AdminPassword = "Aw@" + (python -c "import secrets; print(secrets.token_hex(8))" 2>$null) + "1"
        Write-OK "已生成随机 owner 密码: $AdminPassword"
    }

    $initBody = @{
        username = $AdminUser
        password = $AdminPassword
        nickname = "Administrator"
    } | ConvertTo-Json

    Write-Info "调用 POST /api/system/init 创建 owner..."
    try {
        $initResp = Invoke-WebRequest -Uri "http://localhost:8000/api/system/init" `
            -Method Post -Body $initBody -ContentType "application/json" `
            -TimeoutSec 30 -UseBasicParsing -ErrorAction Stop
        $initData = $initResp.Content | ConvertFrom-Json
        if ($initData.success) {
            Write-OK "初始化完成"
            Write-OK "  用户名: $($initData.data.username)"
            Write-OK "  密码  : $AdminPassword"
            Write-OK "  User ID: $($initData.data.user_id)"
        } else {
            Write-Err "初始化返回非 success"
            Write-Info $initResp.Content
        }
    } catch {
        $errMsg = $_.Exception.Message
        Write-Warn "init 端点调用失败: $errMsg"
        Write-Info "可手动执行:"
        Write-Info "  curl -X POST http://localhost:8000/api/system/init \"
        Write-Info "    -H 'Content-Type: application/json' \"
        Write-Info "    -d '{\"\"username\"\":\"\"$AdminUser\"\",\"\"password\"\":\"\"$AdminPassword\"\"}'"
    }
}

# ============================================================================
# 完成
# ============================================================================
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  部署完成!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "访问地址:" -ForegroundColor Cyan
Write-Host "  后端 API : http://localhost:8000"
Write-Host "  健康检查  : http://localhost:8000/api/system/ping"
if ($Mode -eq "full" -or $Mode -eq "prod") {
    $webProto = "http"
    if ($Mode -eq "prod") { $webProto = "https" }
    Write-Host "  前端页面  : ${webProto}://localhost"
}
Write-Host ""
Write-Host "登录凭据:" -ForegroundColor Cyan
Write-Host "  用户名: $AdminUser"
if ($AdminPassword) {
    Write-Host "  密码  : $AdminPassword"
}
Write-Host ""
Write-Host "常用命令:" -ForegroundColor Cyan
Write-Host "  docker compose ps                        查看状态"
Write-Host "  docker compose logs -f backend           查看日志"
Write-Host "  docker compose down                      停止"
Write-Host "  docker compose down -v                   停止并删除数据（慎用）"
Write-Host ""
Write-Host "配置文件位置: $envFile" -ForegroundColor Cyan
