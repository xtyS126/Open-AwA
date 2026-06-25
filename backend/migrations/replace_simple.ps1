# 简化的提权替换脚本
$ErrorActionPreference = 'Stop'
try {
    $target = 'd:\代码\Open-AwA\backend\migrations\add_memory_layers.py'
    $source = 'd:\代码\Open-AwA\backend\migrations\add_memory_layers_new.py'
    # 先取得所有权
    & takeown /f $target | Out-Null
    # 授予完全控制权限
    & icacls $target /grant "${env:USERNAME}:(F)" | Out-Null
    # 替换文件内容
    $content = Get-Content -Path $source -Raw -Encoding UTF8
    Set-Content -Path $target -Value $content -Encoding UTF8 -NoNewline
    "OK" | Out-File 'd:\代码\Open-AwA\backend\migrations\_done.txt'
} catch {
    "ERR: $($_.Exception.Message)" | Out-File 'd:\代码\Open-AwA\backend\migrations\_done.txt'
}
