# ============================================================
# release-apk.ps1 —— APP 更新包构建与部署脚本
# 用途：同步版本号 -> 构建 APK -> 生成 manifest.json -> 部署到后端 var/apk/
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts/release-apk.ps1 -Changelog "修复说明"
#   powershell -ExecutionPolicy Bypass -File scripts/release-apk.ps1 -Changelog "修复" -VersionCode 3
# ============================================================
param(
    [string]$Changelog = "",
    [int]$VersionCode = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # frontend/
$backendApkDir = Join-Path $root "..\var\apk"
$apkOut = Join-Path $root "android\app\build\outputs\apk\debug\app-debug.apk"
$manifestPath = Join-Path $backendApkDir "manifest.json"

# 1. 读取 package.json 版本
$pkg = Get-Content (Join-Path $root "package.json") -Raw | ConvertFrom-Json
$version = $pkg.version
Write-Host "构建版本: $version"

# 2. versionCode：显式参数优先，否则从 build.gradle 当前 versionCode 递增（首次为 1）
# 递增基准必须用 build.gradle（git 版本控制的真实现状）而非 manifest：
# manifest 可能滞后于设备已装版本（历史上 v0.03 手动构建过 versionCode 5，
# manifest 却停留在 2/3），从 manifest 递增会发布出比设备更低的 versionCode，
# 导致设备端 OTA 检查永远 has_update=false、永不提示更新。
if ($VersionCode -eq 0) {
    $gradle = Join-Path $root "android\app\build.gradle"
    $gradleContent = [System.IO.File]::ReadAllText($gradle, [System.Text.Encoding]::UTF8)
    if ($gradleContent -match 'versionCode (\d+)') {
        $VersionCode = [int]$Matches[1] + 1
    } else {
        $VersionCode = 1
    }
}
Write-Host "versionCode: $VersionCode"

# 3. 同步 build.gradle（versionName / versionCode）
# 注意：PowerShell 5.1 的 Get-Content 无 -Encoding 时按 ANSI(GBK) 解码 UTF-8 文件会破坏中文注释；
# Set-Content -Encoding UTF8 会写入 BOM（Gradle 不认 BOM 报 Unexpected character）。
# 必须显式 UTF8 读取 + WriteAllText 无 BOM 写回。
$gradle = Join-Path $root "android\app\build.gradle"
$content = [System.IO.File]::ReadAllText($gradle, [System.Text.Encoding]::UTF8)
$content = $content -replace 'versionCode \d+', "versionCode $VersionCode"
$content = $content -replace 'versionName "[^"]+"', "versionName `"$version`""
[System.IO.File]::WriteAllText($gradle, $content, (New-Object System.Text.UTF8Encoding $false))
Write-Host "build.gradle 已同步: versionName=$version versionCode=$VersionCode"

# 4. 构建 APK
Push-Location (Join-Path $root "android")
try {
    $env:JAVA_HOME = "D:\Program Files\Java\jdk-21"
    $env:ANDROID_HOME = "D:\Android\Sdk"
    & ".\gradlew.bat" assembleDebug --no-daemon
    if ($LASTEXITCODE -ne 0) { throw "gradle 构建失败" }
} finally {
    Pop-Location
}
if (-not (Test-Path $apkOut)) { throw "APK 产物缺失: $apkOut" }

# 5. 计算 sha256 / size
$sha = (Get-FileHash $apkOut -Algorithm SHA256).Hash.ToLower()
$size = (Get-Item $apkOut).Length
$apkName = "openawa-$version.apk"
Write-Host "APK 产物: $apkOut ($size bytes)"

# 6. 部署到后端 var/apk/（保留新文件，清理同前缀旧文件）
New-Item -ItemType Directory -Force -Path $backendApkDir | Out-Null
Get-ChildItem (Join-Path $backendApkDir "openawa-*.apk") -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne $apkName } |
    Remove-Item -Force
Copy-Item $apkOut (Join-Path $backendApkDir $apkName) -Force

# 7. 生成 manifest.json
$manifest = @{
    version      = $version
    version_code = $VersionCode
    apk          = $apkName
    apk_size     = $size
    apk_sha256   = $sha
    changelog    = $Changelog
    published_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
} | ConvertTo-Json
# manifest.json 必须无 BOM：PowerShell 5.1 的 Set-Content -Encoding UTF8 会写 BOM，
# 后端 Python json.loads 读 BOM 文件会抛异常导致更新检查返回"未部署更新包"
[System.IO.File]::WriteAllText($manifestPath, $manifest, (New-Object System.Text.UTF8Encoding $false))

Write-Host "=========================================="
Write-Host "部署完成: $manifestPath"
Write-Host "APK: $apkName ($size bytes)"
Write-Host "SHA256: $sha"
Write-Host "versionCode: $VersionCode"
Write-Host "=========================================="
