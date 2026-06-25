# 提权替换 add_memory_layers.py 文件的脚本
$targetFile = 'd:\代码\Open-AwA\backend\migrations\add_memory_layers.py'
$sourceFile = 'd:\代码\Open-AwA\backend\migrations\add_memory_layers_new.py'
$markerFile = 'd:\代码\Open-AwA\backend\migrations\_replace_done.marker'

try {
    # 取得文件所有权
    takeown /f $targetFile 2>&1 | Out-Null
    # 授予当前用户完全控制权限
    icacls $targetFile /grant "$env:USERNAME:(F)" 2>&1 | Out-Null
    # 复制新内容到目标文件
    Copy-Item -Path $sourceFile -Destination $targetFile -Force -ErrorAction Stop
    # 创建标记文件表示成功
    "SUCCESS" | Out-File -FilePath $markerFile -Encoding utf8
    exit 0
} catch {
    "FAILED: $($_.Exception.Message)" | Out-File -FilePath $markerFile -Encoding utf8
    exit 1
}
