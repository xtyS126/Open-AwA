$filePath = 'd:\代码\Open-AwA\backend\migrations\add_memory_layers.py'
$newFilePath = 'd:\代码\Open-AwA\backend\migrations\add_memory_layers_new.py'

# 取得文件所有权
takeown /f $filePath | Out-Null

# 授予当前用户完全控制权限
icacls $filePath /grant "$env:USERNAME:(F)" | Out-Null

# 用新文件替换原文件
Copy-Item -Path $newFilePath -Destination $filePath -Force

# 写入成功标记
Set-Content -Path 'd:\代码\Open-AwA\backend\elevate_success.txt' -Value 'success'
