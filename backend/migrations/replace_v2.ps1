# 使用 PSScriptRoot 避免中文路径编码问题
$ErrorActionPreference = 'Stop'
try {
    $scriptDir = $PSScriptRoot
    $target = Join-Path $scriptDir "add_memory_layers.py"
    $source = Join-Path $scriptDir "add_memory_layers_new.py"
    $marker = Join-Path $scriptDir "_done.txt"

    Write-Host "Target: $target"
    Write-Host "Source: $source"

    # 取得所有权
    & takeown /f $target | Out-Null
    # 授予当前用户完全控制权限
    & icacls $target /grant "${env:USERNAME}:(F)" | Out-Null
    # 替换文件内容
    $content = Get-Content -Path $source -Raw -Encoding UTF8
    Set-Content -Path $target -Value $content -Encoding UTF8 -NoNewline
    "OK" | Out-File $marker -Encoding utf8
    Write-Host "SUCCESS"
} catch {
    "ERR: $($_.Exception.Message)" | Out-File $marker -Encoding utf8
    Write-Host "FAILED: $($_.Exception.Message)"
}
