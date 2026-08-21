# ============================================================
# release-apk.ps1 —— APP 更新包构建与部署脚本（原生 Android 项目版）
# 用途：同步版本号 -> 构建 APK -> 生成 manifest.json -> 部署到后端 var/apk/
# 项目迁移说明：2026-07-09 起废弃 Capacitor 方案（frontend/android），
#               现行产物来自原生项目 android/Open-AwA-Android。
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts/release-apk.ps1 -Changelog "修复说明"
#   powershell -ExecutionPolicy Bypass -File scripts/release-apk.ps1 -Changelog "修复" -VersionCode 7
# ============================================================
param(
    [string]$Changelog = "",
    [int]$VersionCode = 0
)

$ErrorActionPreference = "Stop"
# 本脚本位于 <项目根>/frontend/scripts/，原生 Android 项目位于 <项目根>/android/Open-AwA-Android
$frontendDir = Split-Path -Parent $PSScriptRoot            # frontend/
$projectRoot = Split-Path -Parent $frontendDir             # 项目根
$androidProject = Join-Path $projectRoot "android\Open-AwA-Android"
$backendApkDir = Join-Path $projectRoot "var\apk"
$gradleKts = Join-Path $androidProject "app\build.gradle.kts"
$apkOut = Join-Path $androidProject "app\build\outputs\apk\debug\app-debug.apk"
$manifestPath = Join-Path $backendApkDir "manifest.json"

if (-not (Test-Path $gradleKts)) { throw "未找到原生项目构建脚本: $gradleKts" }

# 1. 读取 build.gradle.kts 当前 versionName（原生 App 版本独立于前端 package.json）
$gradleContent = [System.IO.File]::ReadAllText($gradleKts, [System.Text.Encoding]::UTF8)
if ($gradleContent -match 'versionName\s*=\s*"([^"]+)"') {
    $version = $Matches[1]
} else {
    throw "无法从 build.gradle.kts 解析 versionName"
}
Write-Host "构建版本: $version"

# 2. versionCode：显式参数优先，否则从 build.gradle.kts 当前 versionCode 递增（首次为 1）
# 递增基准必须用 build.gradle.kts（git 版本控制的真实现状）而非 manifest：
# manifest 可能滞后于设备已装版本（历史上 v0.03 手动构建过 versionCode 5，
# manifest 却停留在 2/3），从 manifest 递增会发布出比设备更低的 versionCode，
# 导致设备端 OTA 检查永远 has_update=false、永不提示更新。
# 另注意：历史上设备装过的最高 versionCode 为 5，原生项目从 6 起步以压过旧包。
if ($VersionCode -eq 0) {
    if ($gradleContent -match 'versionCode\s*=\s*(\d+)') {
        $VersionCode = [int]$Matches[1] + 1
    } else {
        $VersionCode = 1
    }
}
Write-Host "versionCode: $VersionCode"

# 3. 同步 build.gradle.kts（versionName / versionCode）
# 注意：PowerShell 5.1 的 Get-Content 无 -Encoding 时按 ANSI(GBK) 解码 UTF-8 文件会破坏中文注释；
# Set-Content -Encoding UTF8 会写入 BOM（Gradle 不认 BOM 报 Unexpected character）。
# 必须显式 UTF8 读取 + WriteAllText 无 BOM 写回。
$content = [System.IO.File]::ReadAllText($gradleKts, [System.Text.Encoding]::UTF8)
$content = $content -replace 'versionCode\s*=\s*\d+', "versionCode = $VersionCode"
$content = $content -replace 'versionName\s*=\s*"[^"]+"', "versionName = `"$version`""
[System.IO.File]::WriteAllText($gradleKts, $content, (New-Object System.Text.UTF8Encoding $false))
Write-Host "build.gradle.kts 已同步: versionName=$version versionCode=$VersionCode"

# 4. 构建 APK（JAVA_HOME / ANDROID_HOME 依赖系统环境变量，勿在此硬编码旧路径）
Push-Location $androidProject
try {
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
